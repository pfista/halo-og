package com.halo.decomp;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.net.ssl.HttpsURLConnection;

/** Optional recordings download in the background; game-type audio stays off.
 * One complete pack is installed beneath the existing native save root.
 * No maps, configuration files or user recordings are replaced. */
final class TimerAudio {
    static final String MANIFEST_URL = "https://dl.oghalo.com/audio/timer/v1/current.json";
    static final int MAX_MANIFEST_BYTES = 65536;
    static final int MAX_FILE_BYTES = 1048576;
    static final long MAX_PACK_BYTES = 33554432;
    static final List<String> CUES;
    private static final AtomicBoolean running = new AtomicBoolean();

    static {
        List<String> cues = new ArrayList<>(Arrays.asList("timerbeep", "1_minute"));
        for (int i = 2; i <= 30; i++) cues.add(i + "_minutes");
        cues.add("30_seconds_left"); cues.add("20_seconds");
        for (int i = 10; i > 0; i--) cues.add(Integer.toString(i));
        cues.addAll(Arrays.asList("rocket", "camo", "overshield"));
        CUES = Collections.unmodifiableList(cues);
    }

    interface Status { void changed(String message); }
    interface ConnectionFactory { HttpURLConnection open(URL url) throws IOException; }
    interface Publisher { boolean publish(Path source, Path destination) throws IOException; }
    static final class Entry {
        final String cue, sha256, key;
        final int bytes;
        Entry(String cue, int bytes, String sha256, String key) {
            this.cue = cue; this.bytes = bytes; this.sha256 = sha256; this.key = key;
        }
    }

    private TimerAudio() {}
    private static native boolean publishNoReplace(String source, String destination);
    static boolean publishPack(Path source, Path destination) {
        return publishNoReplace(source.toString(), destination.toString());
    }
    static boolean downloading() { return running.get(); }

    /** Uses the same config.toml location and default-on convention as Updater.
     * The native settings registry writes this boolean; malformed values opt out. */
    static boolean automaticDownloadsEnabled(File config) {
        if (!config.exists()) return true;
        try {
            if (Files.isSymbolicLink(config.toPath()) || !config.isFile() || config.length() > 1048576) return false;
            String section = "";
            for (String line : Files.readAllLines(config.toPath(), StandardCharsets.UTF_8)) {
                String trimmed = line.trim();
                if (trimmed.startsWith("[") && trimmed.contains("]")) {
                    section = trimmed.substring(1, trimmed.indexOf(']')).trim();
                } else if (section.equals("timer_audio") && trimmed.matches("auto_download\\s*=.*")) {
                    String value = trimmed.substring(trimmed.indexOf('=') + 1).split("#", 2)[0].trim();
                    return value.equals("true");
                }
            }
            return true;
        } catch (IOException exception) { return false; }
    }

    /** HaloActivity calls this after SDL has loaded libmain and data is selected.
     * Disk inspection and HTTPS both stay off the Activity/UI and guest threads. */
    static void start(File external, Status status) {
        if (external == null || !running.compareAndSet(false, true)) return;
        Thread thread = new Thread(() -> {
            try {
                Path data = external.toPath().toAbsolutePath().normalize();
                if (!Files.isRegularFile(data.resolve("maps/ui.map"), LinkOption.NOFOLLOW_LINKS)
                    || !automaticDownloadsEnabled(data.resolve("config.toml").toFile())) return;
                download(data.resolve("save"), url -> (HttpURLConnection) url.openConnection(),
                    TimerAudio::publishPack, status);
            } catch (IOException | RuntimeException | LinkageError exception) {
                // Never log untrusted server errors, URL parameters or user paths.
                status.changed("Timer recordings could not be downloaded. Existing files were preserved; Halo will retry next launch.");
            } finally { running.set(false); }
        }, "timer recording download");
        thread.setDaemon(true);
        thread.start();
    }

    static List<Entry> validateManifest(JSONObject manifest) throws IOException {
        try {
            if (!exactKeys(manifest, "schema_version", "pack_id", "files")
                || integer(manifest.get("schema_version"), 1, 1) != 1
                || !"performance-timer-v1".equals(manifest.get("pack_id"))) throw new IOException("Unsupported timer pack");
            Object filesValue = manifest.get("files");
            if (!(filesValue instanceof JSONArray) || ((JSONArray) filesValue).length() != CUES.size())
                throw new IOException("Incomplete timer pack");
            JSONArray files = (JSONArray) filesValue;
            Set<String> seen = new HashSet<>();
            List<Entry> entries = new ArrayList<>();
            long total = 0;
            for (int i = 0; i < files.length(); i++) {
                Object value = files.get(i);
                if (!(value instanceof JSONObject)) throw new IOException("Invalid timer cue");
                JSONObject entry = (JSONObject) value;
                if (!exactKeys(entry, "cue", "file_bytes", "sha256", "object_key")) throw new IOException("Unexpected timer fields");
                Object cueValue = entry.get("cue"), hashValue = entry.get("sha256"), keyValue = entry.get("object_key");
                if (!(cueValue instanceof String) || !(hashValue instanceof String) || !(keyValue instanceof String))
                    throw new IOException("Invalid timer cue identity");
                String cue = (String) cueValue, hash = (String) hashValue, key = (String) keyValue;
                int bytes = (int) integer(entry.get("file_bytes"), 46, MAX_FILE_BYTES);
                if (!CUES.contains(cue) || !seen.add(cue) || !hash.matches("[0-9a-f]{64}")
                    || !key.equals("audio/timer/sha256/" + hash + "/" + cue + ".wav")) throw new IOException("Unsafe timer cue");
                total += bytes;
                if (total > MAX_PACK_BYTES) throw new IOException("Timer pack exceeds its byte limit");
                entries.add(new Entry(cue, bytes, hash, key));
            }
            return entries;
        } catch (JSONException exception) { throw new IOException("Invalid timer manifest"); }
    }

    private static boolean exactKeys(JSONObject value, String... keys) {
        if (value.length() != keys.length) return false;
        for (String key : keys) if (!value.has(key)) return false;
        return true;
    }
    private static long integer(Object value, long minimum, long maximum) throws IOException {
        if (!(value instanceof Integer) && !(value instanceof Long)) throw new IOException("Expected an integer");
        long number = ((Number) value).longValue();
        if (number < minimum || number > maximum) throw new IOException("Integer outside timer bounds");
        return number;
    }

    static boolean validWav(byte[] data) {
        if (data == null || data.length < 46 || data.length > MAX_FILE_BYTES) return false;
        ByteBuffer header = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN);
        int channels = header.getShort(22) & 65535, rate = header.getInt(24), align = header.getShort(32) & 65535;
        long bytes = Integer.toUnsignedLong(header.getInt(40));
        return tag(data, 0, "RIFF") && tag(data, 8, "WAVEfmt ") && tag(data, 36, "data")
            && header.getInt(16) == 16 && header.getShort(20) == 1 && header.getShort(34) == 16
            && (channels == 1 || channels == 2) && (rate == 22050 || rate == 44100) && align == channels * 2
            && header.getInt(28) == rate * align && bytes > 0 && bytes % align == 0 && bytes <= rate * align * 4L
            && Integer.toUnsignedLong(header.getInt(4)) == bytes + 36 && data.length == bytes + 44;
    }
    private static boolean tag(byte[] data, int offset, String expected) {
        for (int i = 0; i < expected.length(); i++) if (data[offset + i] != (byte) expected.charAt(i)) return false;
        return true;
    }
    static String hash(byte[] data) throws IOException {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(data);
            StringBuilder result = new StringBuilder(64);
            for (byte value : digest) result.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            return result.toString();
        } catch (NoSuchAlgorithmException exception) { throw new IOException("SHA-256 unavailable"); }
    }
    private static boolean allowed(URL url) {
        return url.getProtocol().equals("https") && url.getHost().equalsIgnoreCase("dl.oghalo.com")
            && (url.getPort() == -1 || url.getPort() == 443) && url.getUserInfo() == null
            && url.getQuery() == null && url.getRef() == null;
    }

    static byte[] fetch(URL url, int limit, boolean exactLength, long deadline, ConnectionFactory factory) throws IOException {
        if (!allowed(url)) throw new IOException("Unapproved timer URL");
        HttpURLConnection connection = factory.open(url);
        try {
            if (!(connection instanceof HttpsURLConnection)) throw new IOException("Timer HTTPS required");
            connection.setInstanceFollowRedirects(false);
            connection.setUseCaches(false);
            connection.setConnectTimeout(remainingMilliseconds(deadline));
            connection.setReadTimeout(remainingMilliseconds(deadline));
            connection.setRequestProperty("Accept-Encoding", "identity");
            connection.setRequestProperty("User-Agent", "halo-ce-universal-updater");
            if (connection.getResponseCode() != 200 || !allowed(connection.getURL()) || !connection.getURL().equals(url))
                throw new IOException("Unexpected timer HTTPS response");
            String encoding = connection.getHeaderField("Content-Encoding");
            long length = connection.getContentLengthLong();
            if ((encoding != null && !encoding.isEmpty() && !encoding.equalsIgnoreCase("identity"))
                || length > limit || (exactLength && length >= 0 && length != limit)) throw new IOException("Unexpected timer transfer size or encoding");
            try (InputStream input = connection.getInputStream(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[16384];
                int count;
                while (true) {
                    connection.setReadTimeout(remainingMilliseconds(deadline));
                    count = input.read(buffer);
                    if (count < 0) break;
                    if (count > limit - output.size()) throw new IOException("Timer transfer exceeds its byte limit");
                    output.write(buffer, 0, count);
                }
                if (exactLength && output.size() != limit) throw new IOException("Incomplete timer recording");
                return output.toByteArray();
            }
        } finally { connection.disconnect(); }
    }
    private static int remainingMilliseconds(long deadline) throws IOException {
        long remaining = (deadline - System.nanoTime()) / 1000000;
        if (remaining <= 0) throw new IOException("Timer download timed out");
        return (int) Math.min(30000, remaining);
    }

    static boolean completePack(Path pack) throws IOException {
        if (!Files.isDirectory(pack, LinkOption.NOFOLLOW_LINKS)) return false;
        for (String cue : CUES) {
            Path file = pack.resolve(cue + ".wav");
            if (!Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS) || Files.size(file) > MAX_FILE_BYTES) return false;
            try (InputStream input = Files.newInputStream(file, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS);
                 ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[16384];
                int count;
                while ((count = input.read(buffer)) >= 0) {
                    if (count > MAX_FILE_BYTES - output.size()) return false;
                    output.write(buffer, 0, count);
                }
                if (!validWav(output.toByteArray())) return false;
            }
        }
        return true;
    }
    private static void directory(Path path) throws IOException {
        if (!Files.exists(path, LinkOption.NOFOLLOW_LINKS)) Files.createDirectory(path);
        if (!Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Timer directory is a file or link");
    }

    static void download(Path saveRoot, ConnectionFactory factory, Publisher publisher, Status status) throws IOException {
        Path root = saveRoot.toAbsolutePath().normalize();
        directory(root.getParent()); directory(root);
        Path sounds = root.resolve("sounds"), pack = sounds.resolve("performance");
        directory(sounds);
        if (completePack(pack)) return;
        if (Files.exists(pack, LinkOption.NOFOLLOW_LINKS)) {
            status.changed("An existing timer recording folder was preserved. Move it manually before downloading a replacement.");
            return;
        }
        Path stage = sounds.resolve(".performance-download-" + UUID.randomUUID());
        Files.createDirectory(stage);
        boolean installed = false;
        long deadline = System.nanoTime() + 180000000000L;
        try {
            status.changed("Downloading the complete timer recording pack…");
            byte[] manifest = fetch(new URL(MANIFEST_URL), MAX_MANIFEST_BYTES, false, deadline, factory);
            List<Entry> files;
            try { files = validateManifest(new JSONObject(new String(manifest, StandardCharsets.UTF_8))); }
            catch (JSONException exception) { throw new IOException("Invalid timer manifest"); }
            for (Entry entry : files) {
                byte[] audio = fetch(new URL("https://dl.oghalo.com/" + entry.key), entry.bytes, true, deadline, factory);
                if (!validWav(audio) || !hash(audio).equals(entry.sha256)) throw new IOException("Invalid timer recording");
                Files.write(stage.resolve(entry.cue + ".wav"), audio, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
            }
            Files.write(stage.resolve("download-manifest.json"), manifest, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
            if (!publisher.publish(stage, pack)) throw new IOException("Timer destination appeared or atomic publication is unavailable");
            installed = true;
            status.changed("Timer recordings downloaded. If Halo already reported them missing, restart Halo to enable Timer Audio.");
        } finally {
            if (!installed) {
                for (String cue : CUES) Files.deleteIfExists(stage.resolve(cue + ".wav"));
                Files.deleteIfExists(stage.resolve("download-manifest.json"));
                Files.deleteIfExists(stage);
            }
        }
    }
}
