package io.github.darkhanakh.kazsearch;

import java.net.URI;
import java.net.URL;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.AccessController;
import java.security.PrivilegedAction;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Loads the kazsearch native library (Rust cdylib with JNI exports) from the
 * installed plugin directory.
 *
 * The plugin zip ships native libraries in platform directories next to the
 * plugin jar ({@code linux-x86_64/}, {@code linux-aarch64/},
 * {@code darwin-aarch64/}, ...). The loader detects {@code os.name} /
 * {@code os.arch}, resolves the matching library to an absolute path, and
 * calls {@link System#load(String)} — no {@code LD_LIBRARY_PATH} and no
 * post-install copy step are required.
 *
 * The plugin directory is taken from the hint set by the factory (derived
 * from the Elasticsearch {@code Environment}), falling back to parsing this
 * class's own jar URL. Existence checks and {@code getProtectionDomain} are
 * intentionally avoided: both would require permissions that Elasticsearch
 * does not allow plugins to request. Each candidate is passed straight to
 * {@code System.load} and {@link UnsatisfiedLinkError} is treated as "try the
 * next one".
 */
@SuppressWarnings("removal")
final class NativeLibraryLoader {

    private static final String LIBRARY_BASENAME = "kazsearch_elastic";

    /** Overrides the search directory containing platform subdirs (unit tests). */
    private static final String NATIVE_DIR_PROPERTY = "kazsearch.native.dir";

    private static volatile boolean loaded;
    private static volatile Path pluginDirectoryHint;
    private static volatile Path pluginDirectory;

    private NativeLibraryLoader() {
    }

    /**
     * Records the installed plugin directory (e.g. derived from
     * {@code Environment#pluginsFile()}). Must be called before the first
     * {@link #load()} to take effect.
     */
    static void hintPluginDirectory(Path dir) {
        if (dir != null && pluginDirectoryHint == null) {
            pluginDirectoryHint = dir;
        }
    }

    /** Loads the native library exactly once; safe to call repeatedly. */
    static synchronized void load() {
        if (loaded) {
            return;
        }
        AccessController.doPrivileged((PrivilegedAction<Void>) () -> {
            loadWithinPrivileged();
            return null;
        });
        loaded = true;
    }

    /**
     * Directory the plugin is installed in, or {@code null} when it cannot be
     * determined (e.g. unit tests running from an unpacked classes directory).
     */
    static Path pluginDirectory() {
        load();
        return pluginDirectory;
    }

    private static void loadWithinPrivileged() {
        String platform = platformDirectory();
        String fileName = libraryFileName();
        List<String> attempted = new ArrayList<>();

        String override = systemPropertyOrNull(NATIVE_DIR_PROPERTY);
        if (override != null && !override.isEmpty()
                && tryLoad(Paths.get(override, platform, fileName), attempted)) {
            return;
        }

        List<Path> candidates = new ArrayList<>();
        if (pluginDirectoryHint != null) {
            candidates.add(pluginDirectoryHint);
        }
        Path jarDir = jarDirectory();
        if (jarDir != null && !jarDir.equals(pluginDirectoryHint)) {
            candidates.add(jarDir);
        }

        for (Path dir : candidates) {
            if (tryLoad(dir.resolve(platform).resolve(fileName), attempted)
                    // Legacy layout: library copied directly next to the jar.
                    || tryLoad(dir.resolve(fileName), attempted)) {
                pluginDirectory = dir;
                return;
            }
        }

        // Last resort for dev environments: java.library.path.
        try {
            System.loadLibrary(LIBRARY_BASENAME);
            return;
        } catch (UnsatisfiedLinkError e) {
            attempted.add("java.library.path (" + e.getMessage() + ")");
        }

        throw new UnsatisfiedLinkError(
                "Could not load kazsearch native library '" + fileName + "' for platform '"
                        + platform + "'. Attempted: " + String.join(", ", attempted));
    }

    private static boolean tryLoad(Path candidate, List<String> attempted) {
        String absolute = candidate.toAbsolutePath().toString();
        try {
            System.load(absolute);
            return true;
        } catch (UnsatisfiedLinkError e) {
            attempted.add(absolute);
            return false;
        }
    }

    private static String systemPropertyOrNull(String name) {
        try {
            return System.getProperty(name);
        } catch (SecurityException e) {
            return null;
        }
    }

    /** Parses the directory containing this class's jar from its resource URL. */
    private static Path jarDirectory() {
        try {
            URL url = NativeLibraryLoader.class.getResource(
                    NativeLibraryLoader.class.getSimpleName() + ".class");
            if (url == null || !"jar".equals(url.getProtocol())) {
                return null;
            }
            // jar:file:/.../plugins/analysis-kazsearch/analysis-kazsearch-x.y.z.jar!/io/...
            String spec = url.getPath();
            int separator = spec.indexOf("!/");
            if (separator <= 0) {
                return null;
            }
            return Paths.get(URI.create(spec.substring(0, separator))).getParent();
        } catch (RuntimeException e) {
            return null;
        }
    }

    private static String platformDirectory() {
        return osDirectory() + "-" + archDirectory();
    }

    private static String osDirectory() {
        String os = System.getProperty("os.name", "").toLowerCase(Locale.ROOT);
        if (os.contains("linux")) {
            return "linux";
        }
        if (os.contains("mac") || os.contains("darwin")) {
            return "darwin";
        }
        throw new UnsatisfiedLinkError("Unsupported OS for kazsearch native library: " + os);
    }

    private static String archDirectory() {
        String arch = System.getProperty("os.arch", "").toLowerCase(Locale.ROOT);
        switch (arch) {
            case "amd64":
            case "x86_64":
                return "x86_64";
            case "aarch64":
            case "arm64":
                return "aarch64";
            default:
                throw new UnsatisfiedLinkError(
                        "Unsupported architecture for kazsearch native library: " + arch);
        }
    }

    private static String libraryFileName() {
        return "darwin".equals(osDirectory())
                ? "lib" + LIBRARY_BASENAME + ".dylib"
                : "lib" + LIBRARY_BASENAME + ".so";
    }
}
