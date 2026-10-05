package com.halo.decomp;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;

/** Preserves the complete invite until the native game's next file poll. */
final class InviteLink {
    private static final String PREFIX = "halo-og://join/";
    private static final int CODE_SIZE = 64;

    private InviteLink() {}

    static boolean deliver(File dataRoot, String link) {
        if (dataRoot == null || link == null || link.length() != PREFIX.length() + CODE_SIZE
            || !link.regionMatches(true, 0, PREFIX, 0, PREFIX.length()))
            return false;
        for (int i = PREFIX.length(); i < link.length(); i++) {
            char c = link.charAt(i);
            if (!(c >= '0' && c <= '9') && !(c >= 'a' && c <= 'f') && !(c >= 'A' && c <= 'F'))
                return false;
        }
        File partial = null;
        try {
            // Unique staging files preserve a complete invite if another
            // launcher delivery occurs before the game consumes this one.
            partial = File.createTempFile("join_link.", ".tmp", dataRoot);
            try (FileOutputStream out = new FileOutputStream(partial)) {
                out.write(link.getBytes(StandardCharsets.UTF_8));
            }
            Files.move(partial.toPath(), new File(dataRoot, "join_link.txt").toPath(),
                StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            return true;
        } catch (IOException e) {
            return false;
        } finally {
            if (partial != null)
                partial.delete();
        }
    }
}
