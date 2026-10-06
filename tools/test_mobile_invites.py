"""Check mobile URI registration and execute Android launch delivery offline."""
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "port/android/app/src/main"
ANDROID_ATTRIBUTE = "{http://schemas.android.com/apk/res/android}"


def java_method(source, declaration):
    """Use the production method unchanged in the small JVM lifecycle fixture."""
    start = source.index(declaration)
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
        end += 1
    return source[start:end]


class MobileInviteRegistrationTests(unittest.TestCase):
    def test_android_claims_only_og_invites_and_can_reuse_launcher(self):
        application = ET.parse(ANDROID / "AndroidManifest.xml").getroot().find("application")
        launcher = next(activity for activity in application.findall("activity")
                        if activity.get(ANDROID_ATTRIBUTE + "name") == ".LauncherActivity")
        self.assertEqual(launcher.get(ANDROID_ATTRIBUTE + "launchMode"), "singleTop")
        view = next(intent for intent in launcher.findall("intent-filter")
                    if any(action.get(ANDROID_ATTRIBUTE + "name") == "android.intent.action.VIEW"
                           for action in intent.findall("action")))
        self.assertEqual({category.get(ANDROID_ATTRIBUTE + "name")
                          for category in view.findall("category")},
                         {"android.intent.category.DEFAULT", "android.intent.category.BROWSABLE"})
        data = view.findall("data")
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0].get(ANDROID_ATTRIBUTE + "scheme"), "halo-og")
        self.assertEqual(data[0].get(ANDROID_ATTRIBUTE + "host"), "join")
        game = next(activity for activity in application.findall("activity")
                    if activity.get(ANDROID_ATTRIBUTE + "name") == ".HaloActivity")
        self.assertEqual(game.get(ANDROID_ATTRIBUTE + "launchMode"), "singleInstance")

    def test_ios_registers_only_og_invites_and_uses_own_default_identity(self):
        info = plistlib.loads((ROOT / "port/ios/Info.plist.in").read_bytes())
        self.assertEqual([scheme for entry in info["CFBundleURLTypes"]
                          for scheme in entry["CFBundleURLSchemes"]], ["halo-og"])
        self.assertEqual(info["CFBundleURLTypes"][0]["CFBundleTypeRole"], "Viewer")
        scenes = info["UIApplicationSceneManifest"]
        self.assertFalse(scenes["UIApplicationSupportsMultipleScenes"])
        self.assertEqual(scenes["UISceneConfigurations"]["UIWindowSceneSessionRoleApplication"][0]
                         ["UISceneDelegateClassName"], "SDLUIKitSceneDelegate")
        for filename in ("tools/ios_build.py", "port/ios/CMakeLists.txt"):
            self.assertIn("local.halo.og.ios", (ROOT / filename).read_text())

    def test_ios_build_includes_the_shared_native_url_bridge(self):
        cmake = (ROOT / "port/ios/CMakeLists.txt").read_text()
        self.assertIn('file(GLOB HOST_SOURCES "${HALO_ROOT}/port/macos/host/*.c")', cmake)
        self.assertIn('host_(main|loader)', cmake)
        bridge = (ROOT / "port/macos/host/host_sdl.c").read_text()
        poll = java_method(bridge, "int host_sdl_poll_event(")
        self.assertIn("host_invite_received(host_event.drop.data)", poll)
        # The preceding Mac-only keyboard branch ends before URL delivery.
        self.assertLess(poll.index("#endif"), poll.index("host_invite_received"))


class AndroidInviteLifecycleTests(unittest.TestCase):
    def test_cold_and_reused_launcher_preserve_complete_invites(self):
        javac = shutil.which("javac")
        if not javac or subprocess.run([javac, "-version"], capture_output=True).returncode:
            self.skipTest("A real JDK is required for the Android JVM lifecycle fixture")
        source = (ANDROID / "java/com/halo/decomp/LauncherActivity.java").read_text()
        methods = "\n".join(java_method(source, declaration) for declaration in (
            "protected void onCreate(", "protected void onNewIntent(",
            "private void passOnInvite(", "private boolean haveData(", "private void startGame("))
        fixture = r'''
package com.halo.decomp;
import java.io.File;
import java.nio.file.Files;
import java.nio.charset.StandardCharsets;

class Bundle {}
class Button {
    boolean enabled = true;
    boolean isEnabled() { return enabled; }
}
class Uri {
    private final String value;
    Uri(String value) { this.value = value; }
    public String toString() { return value; }
}
class Intent {
    static final String ACTION_VIEW = "android.intent.action.VIEW";
    private final String action;
    private final Uri data;
    final boolean game;
    Intent(String action, String value) {
        this.action = action; this.data = value == null ? null : new Uri(value); game = false;
    }
    Intent(Object context, Class<?> target) { action = null; data = null; game = true; }
    String getAction() { return action; }
    Uri getData() { return data; }
}
class HaloActivity {}
class Activity {
    File root;
    Intent intent;
    int games, finishes;
    protected void onCreate(Bundle saved) {}
    protected void onNewIntent(Intent value) {}
    File getExternalFilesDir(Object ignored) { return root; }
    Intent getIntent() { return intent; }
    void setIntent(Intent value) { intent = value; }
    void startActivity(Intent value) { if (!value.game) throw new AssertionError(); games++; }
    void finish() { finishes++; }
}
class LauncherActivity extends Activity {
    private File dataRoot;
    Button pick;
    int interfaces;
    private void passOnHardwareId() {}
    private void buildInterface() { interfaces++; pick = new Button(); }
    /*PRODUCTION_METHODS*/
}
public class MobileInviteTest {
    static void check(boolean condition) { if (!condition) throw new AssertionError(); }
    static String delivered(File root) throws Exception {
        return new String(Files.readAllBytes(new File(root, "join_link.txt").toPath()), StandardCharsets.UTF_8);
    }
    public static void main(String[] args) throws Exception {
        File root = new File(args[0]);
        root.mkdirs();
        String first = "halo-og://join/" + "0123456789abcdef".repeat(4);
        String second = "HALO-OG://JOIN/" + "FEDCBA9876543210".repeat(4);
        check(first.length() == 79 && second.length() == 79);
        LauncherActivity missing = new LauncherActivity();
        missing.root = root; missing.intent = new Intent(Intent.ACTION_VIEW, first);
        missing.onCreate(null);
        check(missing.interfaces == 1 && missing.games == 0 && delivered(root).equals(first));
        missing.onNewIntent(new Intent(Intent.ACTION_VIEW, second));
        check(missing.games == 0 && delivered(root).equals(second));
        check(missing.getIntent().getData().toString().equals(second));
        new File(root, "maps/ui.map").createNewFile();
        missing.pick.enabled = false;
        missing.onNewIntent(new Intent(Intent.ACTION_VIEW, first));
        check(missing.games == 0 && delivered(root).equals(first));
        LauncherActivity cold = new LauncherActivity();
        cold.root = root; cold.intent = new Intent(Intent.ACTION_VIEW, first);
        cold.onCreate(null);
        check(cold.games == 1 && cold.finishes == 1 && delivered(root).equals(first));
        cold.onNewIntent(new Intent(Intent.ACTION_VIEW, second));
        check(cold.games == 2 && cold.finishes == 2 && delivered(root).equals(second));
        cold.onNewIntent(new Intent("unrelated", first));
        cold.onNewIntent(new Intent(Intent.ACTION_VIEW, (String)null));
        check(delivered(root).equals(second));
        for (String invalid : new String[] {
            "halo://join/" + "a".repeat(64), first.substring(0, 78), first + "a",
            "halo-og://other/" + "a".repeat(64), "halo-og://join/" + "g".repeat(64),
            first + "?query=1", first + "#fragment"}) {
            check(!InviteLink.deliver(root, invalid));
            check(delivered(root).equals(second));
        }
        check(!InviteLink.deliver(null, first) && !InviteLink.deliver(root, null));
        check(!InviteLink.deliver(new File(root, "absent"), first));
        check(root.list((directory, name) -> name.endsWith(".tmp")).length == 0);
        System.out.println("Android cold/reused launcher and complete 79-byte invite delivery passed");
    }
}
'''.replace("/*PRODUCTION_METHODS*/", methods)
        with tempfile.TemporaryDirectory(prefix="halo-mobile-invite-") as temporary:
            out = Path(temporary)
            test = out / "MobileInviteTest.java"
            test.write_text(fixture)
            result = subprocess.run([javac, "-d", str(out), str(test),
                                     str(ANDROID / "java/com/halo/decomp/InviteLink.java")],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            java = str(Path(javac).with_name("java"))
            result = subprocess.run([java, "-cp", str(out), "com.halo.decomp.MobileInviteTest",
                                     str(out / "data")], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("complete 79-byte invite delivery passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
