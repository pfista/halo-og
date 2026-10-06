package com.halo.decomp;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.URL;
import java.net.URLConnection;
import java.net.URLStreamHandler;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.Principal;
import java.security.cert.Certificate;
import java.util.HashMap;
import java.util.Map;
import javax.net.ssl.HttpsURLConnection;

/** Runs production parsing/transfer code with synthetic HTTPS and PCM data.
 * JNI atomic publication is the real Linux host helper, not a simulated move. */
public final class TimerAudioTest {
    private static final Map<String, Response> responses = new HashMap<>();
    private static int requests;
    private static byte[] audio;
    private static JSONObject manifest;

    private static final class Response {
        byte[] data;
        int status = 200;
        String encoding;
        long length;
        Response(byte[] data) { this.data = data; this.length = data.length; }
    }
    private static final class Connection extends HttpsURLConnection {
        private Response response;
        Connection(URL url) { super(url); }
        @Override public int getResponseCode() {
            requests++;
            assert !getInstanceFollowRedirects() && !getUseCaches();
            assert "identity".equals(getRequestProperty("Accept-Encoding"));
            response = responses.get(url.toString());
            return response == null ? 404 : response.status;
        }
        @Override public long getContentLengthLong() { return response == null ? 0 : response.length; }
        @Override public String getHeaderField(String name) { return "Content-Encoding".equals(name) && response != null ? response.encoding : null; }
        @Override public InputStream getInputStream() { return new ByteArrayInputStream(response.data); }
        @Override public void disconnect() {}
        @Override public boolean usingProxy() { return false; }
        @Override public void connect() {}
        @Override public String getCipherSuite() { return "fixture"; }
        @Override public Certificate[] getLocalCertificates() { return null; }
        @Override public Certificate[] getServerCertificates() { return new Certificate[0]; }
        @Override public Principal getPeerPrincipal() { return null; }
        @Override public Principal getLocalPrincipal() { return null; }
    }
    private static byte[] wav() {
        byte[] data = new byte[172];
        ByteBuffer header = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN);
        System.arraycopy("RIFF".getBytes(StandardCharsets.US_ASCII), 0, data, 0, 4);
        System.arraycopy("WAVEfmt ".getBytes(StandardCharsets.US_ASCII), 0, data, 8, 8);
        System.arraycopy("data".getBytes(StandardCharsets.US_ASCII), 0, data, 36, 4);
        header.putInt(4, 164).putInt(16, 16).putShort(20, (short)1).putShort(22, (short)1);
        header.putInt(24, 22050).putInt(28, 44100).putShort(32, (short)2).putShort(34, (short)16).putInt(40, 128);
        for (int i = 44; i < data.length; i++) data[i] = (byte)i;
        return data;
    }
    private static JSONObject manifest(byte[] data) throws Exception {
        JSONArray files = new JSONArray();
        String hash = TimerAudio.hash(data);
        for (String cue : TimerAudio.CUES) files.put(new JSONObject().put("cue", cue).put("file_bytes", data.length)
            .put("sha256", hash).put("object_key", "audio/timer/sha256/" + hash + "/" + cue + ".wav"));
        return new JSONObject().put("schema_version", 1).put("pack_id", "performance-timer-v1").put("files", files);
    }
    private static void fixtures(JSONObject value, byte[] data) throws Exception {
        responses.clear();
        responses.put(TimerAudio.MANIFEST_URL, new Response(value.toString().getBytes(StandardCharsets.UTF_8)));
        for (TimerAudio.Entry entry : TimerAudio.validateManifest(value)) responses.put("https://dl.oghalo.com/" + entry.key, new Response(data));
    }
    private static JSONObject copy(JSONObject value) { return new JSONObject(value.toString()); }
    private static void rejects(JSONObject value) throws Exception {
        try { TimerAudio.validateManifest(value); throw new AssertionError("Accepted an invalid manifest"); }
        catch (IOException expected) {}
    }
    private static void noPackOrStage(Path save) throws Exception {
        Path sounds = save.resolve("sounds");
        if (Files.exists(sounds)) try (java.util.stream.Stream<Path> entries = Files.list(sounds)) {
            assert entries.noneMatch(path -> path.getFileName().toString().equals("performance") || path.getFileName().toString().startsWith(".performance-download-"));
        }
    }
    private static void expectFailedDownload(Path save) throws Exception {
        try { TimerAudio.download(save, Connection::new, TimerAudio::publishPack, message -> {}); throw new AssertionError("Activated an invalid pack"); }
        catch (IOException expected) {}
        noPackOrStage(save);
    }
    private static void waitForBackground() throws Exception {
        long deadline = System.nanoTime() + 5000000000L;
        while (TimerAudio.downloading() && System.nanoTime() < deadline) Thread.sleep(5);
        assert !TimerAudio.downloading();
    }
    public static void main(String[] arguments) throws Exception {
        assert arguments.length == 2;
        Path root = Paths.get(arguments[0]);
        System.load(Paths.get(arguments[1]).toAbsolutePath().toString());
        // All JVM URL connections stay inside this fixture, including start().
        URL.setURLStreamHandlerFactory(protocol -> "https".equals(protocol) ? new URLStreamHandler() {
            @Override protected URLConnection openConnection(URL url) { return new Connection(url); }
        } : null);
        audio = wav(); manifest = manifest(audio);
        assert TimerAudio.CUES.size() == 46 && TimerAudio.validWav(audio);
        assert TimerAudio.validateManifest(new JSONObject(manifest.toString())).size() == 46;
        JSONObject missing = copy(manifest); missing.getJSONArray("files").remove(45); rejects(missing);
        JSONObject duplicate = copy(manifest); duplicate.getJSONArray("files").put(45, duplicate.getJSONArray("files").get(0)); rejects(duplicate);
        for (Object size : new Object[]{true, 172.0, 172.5, 45, 1048577, "172"}) {
            JSONObject bad = copy(manifest); bad.getJSONArray("files").getJSONObject(0).put("file_bytes", size); rejects(bad);
        }
        for (Object schema : new Object[]{true, 1.0, 2, "1"}) { JSONObject bad = copy(manifest); bad.put("schema_version", schema); rejects(bad); }
        for (String cue : new String[]{"../unsafe", "TimerBeep", "unknown", "timerbeep?query"}) {
            JSONObject bad = copy(manifest); bad.getJSONArray("files").getJSONObject(0).put("cue", cue); rejects(bad);
        }
        JSONObject unsafe = copy(manifest); unsafe.getJSONArray("files").getJSONObject(0).put("object_key", "../timerbeep.wav"); rejects(unsafe);
        JSONObject extra = copy(manifest); extra.put("unexpected", true); rejects(extra);
        JSONObject extraEntry = copy(manifest); extraEntry.getJSONArray("files").getJSONObject(0).put("unexpected", true); rejects(extraEntry);
        JSONObject huge = copy(manifest);
        for (int i = 0; i < 46; i++) huge.getJSONArray("files").getJSONObject(i).put("file_bytes", 1048576);
        rejects(huge);
        byte[] badWav = audio.clone(); badWav[20] = 3; assert !TimerAudio.validWav(badWav);
        for (int offset : new int[]{4, 16, 22, 24, 28, 32, 34, 40}) {
            byte[] invalid = audio.clone(); invalid[offset] ^= 255; assert !TimerAudio.validWav(invalid);
        }

        fixtures(manifest, audio);
        Path success = root.resolve("success/save"); Files.createDirectories(success.getParent());
        TimerAudio.download(success, Connection::new, TimerAudio::publishPack, message -> {});
        assert TimerAudio.completePack(success.resolve("sounds/performance")) && requests == 47;
        int before = requests;
        TimerAudio.download(success, Connection::new, TimerAudio::publishPack, message -> {});
        assert requests == before; // Already installed reuses disk without HTTP.

        for (String kind : new String[]{"missing", "hash", "pcm", "gzip", "redirect", "length", "overflow", "manifest", "manifest-overflow"}) {
            JSONObject current = manifest(kind.equals("pcm") ? badWav : audio);
            fixtures(current, kind.equals("pcm") ? badWav : audio);
            String key = "https://dl.oghalo.com/" + current.getJSONArray("files").getJSONObject(45).getString("object_key");
            Response response = responses.get(key);
            if (kind.equals("missing")) responses.remove(key);
            if (kind.equals("hash")) { response.data = audio.clone(); response.data[100] ^= 1; }
            if (kind.equals("gzip")) response.encoding = "gzip";
            if (kind.equals("redirect")) response.status = 302;
            if (kind.equals("length")) response.length = 100;
            if (kind.equals("overflow")) { response.data = java.util.Arrays.copyOf(audio, 173); response.length = -1; }
            if (kind.equals("manifest")) responses.put(TimerAudio.MANIFEST_URL, new Response("{bad".getBytes(StandardCharsets.UTF_8)));
            if (kind.equals("manifest-overflow")) { Response large = new Response(new byte[65537]); large.length = -1; responses.put(TimerAudio.MANIFEST_URL, large); }
            Path save = root.resolve(kind + "/save"); Files.createDirectories(save.getParent());
            expectFailedDownload(save);
        }
        fixtures(manifest, audio);
        Path retry = root.resolve("hash/save");
        TimerAudio.download(retry, Connection::new, TimerAudio::publishPack, message -> {});
        assert TimerAudio.completePack(retry.resolve("sounds/performance"));

        // Preserve an incomplete user folder, a file and a symlink before HTTP.
        Path existing = root.resolve("existing/save"), pack = existing.resolve("sounds/performance");
        Files.createDirectories(pack); Files.write(pack.resolve("keep.txt"), new byte[]{17}); before = requests;
        TimerAudio.download(existing, Connection::new, TimerAudio::publishPack, message -> {});
        assert requests == before && Files.readAllBytes(pack.resolve("keep.txt"))[0] == 17;
        Path fileSave = root.resolve("file/save"); Files.createDirectories(fileSave.resolve("sounds"));
        Files.write(fileSave.resolve("sounds/performance"), new byte[]{19});
        TimerAudio.download(fileSave, Connection::new, TimerAudio::publishPack, message -> {});
        assert requests == before && Files.readAllBytes(fileSave.resolve("sounds/performance"))[0] == 19;
        Path linkSave = root.resolve("link/save"); Files.createDirectories(linkSave.resolve("sounds"));
        Files.createSymbolicLink(linkSave.resolve("sounds/performance"), pack);
        TimerAudio.download(linkSave, Connection::new, TimerAudio::publishPack, message -> {}); assert requests == before;
        Path raced = root.resolve("raced/save"); Files.createDirectories(raced.getParent());
        try {
            TimerAudio.download(raced, Connection::new, (source, destination) -> {
                Files.createDirectory(destination); Files.write(destination.resolve("keep.txt"), new byte[]{23});
                return TimerAudio.publishPack(source, destination);
            }, message -> {});
            throw new AssertionError("Replaced a raced user folder");
        } catch (IOException expected) {}
        assert Files.readAllBytes(raced.resolve("sounds/performance/keep.txt"))[0] == 23;
        try (java.util.stream.Stream<Path> contents = Files.list(raced.resolve("sounds"))) {
            assert contents.noneMatch(path -> path.getFileName().toString().startsWith(".performance-download-"));
        }

        // Default-on startup runs on its own thread after data is selected.
        Path automatic = root.resolve("automatic"); Files.createDirectories(automatic.resolve("maps"));
        Files.write(automatic.resolve("maps/ui.map"), new byte[]{1});
        Path config = automatic.resolve("config.toml");
        Files.write(config, "[timer_audio]\nauto_download = false # opted out\n".getBytes(StandardCharsets.UTF_8));
        assert !TimerAudio.automaticDownloadsEnabled(config.toFile());
        before = requests; TimerAudio.start(automatic.toFile(), message -> {}); waitForBackground(); assert requests == before;
        Files.delete(config); assert TimerAudio.automaticDownloadsEnabled(config.toFile());
        fixtures(manifest, audio); TimerAudio.start(automatic.toFile(), message -> {}); waitForBackground();
        assert TimerAudio.completePack(automatic.resolve("save/sounds/performance")) && requests == before + 47;
        System.out.println("Android Timer Audio real JSON, HTTPS, auto opt-out, PCM and JNI no-replace fixtures passed.");
    }
}
