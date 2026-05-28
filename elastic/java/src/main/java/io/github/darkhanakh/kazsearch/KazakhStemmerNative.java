package io.github.darkhanakh.kazsearch;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.AccessController;
import java.security.PrivilegedAction;

@SuppressWarnings("removal")
public final class KazakhStemmerNative {
    private static final String LIBRARY_BASENAME = "kazsearch_elastic";

    static {
        AccessController.doPrivileged((PrivilegedAction<Void>) () -> {
            loadNativeLibrary();
            return null;
        });
        int initCode = init0("");
        if (initCode != 0) {
            throw new IllegalStateException("Failed to initialize native kazsearch stemmer: " + initCode);
        }
    }

    private static void loadNativeLibrary() {
        // Try System.loadLibrary first (works when LD_LIBRARY_PATH is set)
        try {
            System.loadLibrary(LIBRARY_BASENAME);
            return;
        } catch (UnsatisfiedLinkError ignored) {
            // Fall through to platform-specific resource loading
        }

        // Detect platform and load from bundled resources
        String os = System.getProperty("os.name", "").toLowerCase();
        String arch = System.getProperty("os.arch", "");

        String platformOs;
        String ext;
        if (os.contains("linux")) {
            platformOs = "linux";
            ext = "so";
        } else if (os.contains("mac") || os.contains("darwin")) {
            platformOs = "darwin";
            ext = "dylib";
        } else {
            throw new UnsatisfiedLinkError("Unsupported OS for kazsearch: " + os);
        }

        String platformArch;
        if (arch.equals("amd64") || arch.equals("x86_64")) {
            platformArch = "x86_64";
        } else if (arch.equals("aarch64") || arch.equals("arm64")) {
            platformArch = "aarch64";
        } else {
            throw new UnsatisfiedLinkError("Unsupported architecture for kazsearch: " + arch);
        }

        String libName = "lib" + LIBRARY_BASENAME + "." + ext;
        String resourcePath = "/native/" + platformOs + "-" + platformArch + "/" + libName;

        try (InputStream is = KazakhStemmerNative.class.getResourceAsStream(resourcePath)) {
            if (is == null) {
                throw new UnsatisfiedLinkError(
                    "Native library not found for " + platformOs + "-" + platformArch +
                    ". Resource: " + resourcePath);
            }

            Path tmpLib = Files.createTempFile("kazsearch_", "." + ext);
            tmpLib.toFile().deleteOnExit();
            Files.copy(is, tmpLib, StandardCopyOption.REPLACE_EXISTING);
            System.load(tmpLib.toAbsolutePath().toString());
        } catch (IOException e) {
            throw new UnsatisfiedLinkError("Failed to extract native library: " + e.getMessage());
        }
    }

    private KazakhStemmerNative() {
    }

    public static int init(String lexiconPath) {
        return init0(lexiconPath == null ? "" : lexiconPath);
    }

    public static String stem(String token) {
        if (token == null || token.isEmpty()) {
            return token == null ? "" : token;
        }
        String stemmed = stem0(token);
        return stemmed == null ? token : stemmed;
    }

    private static native int init0(String lexiconPath);

    private static native String stem0(String token);
}
