package com.kinlin.ai.integration;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.Locale;
import java.util.Optional;
import java.util.concurrent.TimeUnit;
import java.util.stream.Stream;

/**
 * 测试自管的真实 Redis 临时实例（零 Docker / 零 Testcontainers）。
 *
 * <p>Windows 用 N03 同源 Memurai（本机 ZhiyiNative 依赖包），Linux/CI 用
 * redis-server；在临时目录写最小配置（loopback、随机端口、无 AUTH，与既有
 * 集成测试前提一致），由测试 JVM 自己 spawn。{@link #stop()} 停的是本进程树
 * 自己启动的服务，{@link #restart()} 复用同一端口重启，供降级测试使用。</p>
 */
public final class NativeRedis implements AutoCloseable {

    private static final boolean WINDOWS =
            System.getProperty("os.name", "").toLowerCase(Locale.ROOT).contains("win");
    private static final int STARTUP_TIMEOUT_SECONDS = 60;

    private final Path executable;
    private final Path root;
    private final int port;
    private final String description;
    private Process process;
    private boolean closed;

    private NativeRedis(Path executable, Path root, int port, String description) {
        this.executable = executable;
        this.root = root;
        this.port = port;
        this.description = description;
    }

    public static NativeRedis start() {
        Path executable;
        try {
            executable = locateBinary();
        } catch (RuntimeException failure) {
            throw new IllegalStateException(
                    "BLOCKED_BY_REDIS: 找不到 Memurai/redis-server 本机二进制（不再使用 Docker/Testcontainers）。"
                            + "设置 ZHIYI_REDIS_BIN，或准备 ZhiyiNative Memurai 依赖包 / 在 CI 安装 redis-server。"
                            + "原因: " + failure.getMessage(),
                    failure);
        }
        Path root;
        try {
            root = Files.createTempDirectory("kinlin-redis-it-");
        } catch (IOException failure) {
            throw new IllegalStateException("BLOCKED_BY_REDIS: 无法创建 Redis 临时目录", failure);
        }
        int port = freePort();
        NativeRedis instance = new NativeRedis(executable, root, port, describe(executable));
        try {
            instance.startProcess();
            instance.awaitReady();
            Runtime.getRuntime().addShutdownHook(
                    new Thread(instance::closeQuietly, "native-redis-test-instance-stop"));
            return instance;
        } catch (IOException failure) {
            instance.stop();
            deleteRecursively(root);
            throw new IllegalStateException("BLOCKED_BY_REDIS: Redis 临时实例启动失败: "
                    + failure.getMessage(), failure);
        } catch (RuntimeException failure) {
            instance.stop();
            deleteRecursively(root);
            throw failure;
        }
    }

    public String getHost() {
        return "127.0.0.1";
    }

    public int getPort() {
        return port;
    }

    public String describe() {
        return description + " (native test instance, port " + port + ")";
    }

    /** 停掉本次测试自己 spawn 的 Redis（供 “Redis 不可用降级” 测试使用）。 */
    public synchronized void stop() {
        if (process == null) {
            return;
        }
        try (Socket socket = new Socket()) {
            socket.connect(new InetSocketAddress(getHost(), port), 500);
            socket.setSoTimeout(500);
            OutputStream out = socket.getOutputStream();
            out.write("SHUTDOWN NOSAVE\r\n".getBytes(StandardCharsets.US_ASCII));
            out.flush();
            try (InputStream ignored = socket.getInputStream()) {
                ignored.read();
            } catch (IOException ignored) {
                // Redis 关闭连接前可能不回包。
            }
        } catch (IOException alreadyDown) {
            // 进程可能已退出；下面统一等待/强制结束。
        }
        try {
            if (!process.waitFor(20, TimeUnit.SECONDS)) {
                process.destroy();
                if (!process.waitFor(10, TimeUnit.SECONDS)) {
                    process.destroyForcibly();
                    process.waitFor(10, TimeUnit.SECONDS);
                }
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            process.destroyForcibly();
        }
        process = null;
    }

    /** 复用同一端口重启（应用上下文持有旧端口，重启后仍指向同一实例地址）。 */
    public synchronized void restart() {
        if (closed) {
            throw new IllegalStateException("Redis test instance already closed");
        }
        if (process != null && process.isAlive()) {
            throw new IllegalStateException("Redis test instance is already running");
        }
        try {
            startProcess();
            awaitReady();
        } catch (IOException failure) {
            throw new IllegalStateException("BLOCKED_BY_REDIS: Redis 临时实例重启失败", failure);
        }
    }

    @Override
    public synchronized void close() {
        if (closed) {
            return;
        }
        closed = true;
        stop();
        deleteRecursively(root);
    }

    private void closeQuietly() {
        try {
            close();
        } catch (RuntimeException ignored) {
            // JVM 退出路径不因清理失败而改变退出码。
        }
    }

    private void startProcess() throws IOException {
        Path config = root.resolve("redis.conf");
        Path data = root.resolve("data");
        Files.createDirectories(data);
        String path = data.toAbsolutePath().toString().replace('\\', '/');
        Files.writeString(config, """
                bind 127.0.0.1
                protected-mode yes
                port %d
                dir "%s"
                dbfilename dump.rdb
                appendonly no
                save ""
                """.formatted(port, path), StandardCharsets.UTF_8);
        process = new ProcessBuilder(executable.toString(), config.toString())
                .redirectErrorStream(true)
                .redirectOutput(root.resolve("redis.log").toFile())
                .start();
    }

    private void awaitReady() {
        long deadline = System.nanoTime() + STARTUP_TIMEOUT_SECONDS * 1_000_000_000L;
        while (System.nanoTime() < deadline) {
            if (!process.isAlive()) {
                throw new IllegalStateException("BLOCKED_BY_REDIS: redis 进程提前退出。\n"
                        + tail(root.resolve("redis.log")));
            }
            if (ping()) {
                return;
            }
            sleepQuietly(150);
        }
        throw new IllegalStateException("BLOCKED_BY_REDIS: Redis 临时实例 %ds 内未就绪。\n%s"
                .formatted(STARTUP_TIMEOUT_SECONDS, tail(root.resolve("redis.log"))));
    }

    private boolean ping() {
        try (Socket socket = new Socket()) {
            socket.connect(new InetSocketAddress(getHost(), port), 300);
            socket.setSoTimeout(300);
            OutputStream out = socket.getOutputStream();
            out.write("PING\r\n".getBytes(StandardCharsets.US_ASCII));
            out.flush();
            byte[] buffer = new byte[64];
            int read = socket.getInputStream().read(buffer);
            return read > 0 && new String(buffer, 0, read, StandardCharsets.US_ASCII).startsWith("+PONG");
        } catch (IOException notReady) {
            return false;
        }
    }

    private static String describe(Path executable) {
        String name = executable.getFileName().toString().toLowerCase(Locale.ROOT);
        if (name.startsWith("memurai")) {
            Path parent = executable.getParent();
            if (parent != null && parent.getFileName().toString().startsWith("memurai-")) {
                String version = parent.getFileName().toString().substring("memurai-".length());
                return "Memurai " + version;
            }
            return "Memurai";
        }
        return "redis-server";
    }

    /** 定位 Redis 二进制：env → ZhiyiNative Memurai 依赖包 → PATH 上的 redis-server。 */
    static Path locateBinary() {
        String configured = System.getenv("ZHIYI_REDIS_BIN");
        if (configured != null && !configured.isBlank()) {
            Path candidate = Path.of(configured);
            if (Files.isDirectory(candidate)) {
                candidate = candidate.resolve(WINDOWS ? "memurai.exe" : "redis-server");
            }
            if (Files.isRegularFile(candidate)) {
                return candidate.toAbsolutePath();
            }
            throw new IllegalStateException("ZHIYI_REDIS_BIN 不是可用的 Redis/Memurai 可执行文件: " + configured);
        }

        String localAppData = System.getenv("LOCALAPPDATA");
        if (WINDOWS && localAppData != null && !localAppData.isBlank()) {
            Path dependencies = Path.of(localAppData, "ZhiyiNative", "dependencies");
            if (Files.isDirectory(dependencies)) {
                try (Stream<Path> children = Files.list(dependencies)) {
                    Optional<Path> found = children.filter(Files::isDirectory)
                            .filter(path -> path.getFileName().toString().startsWith("memurai-"))
                            .max(Comparator.comparing(path -> path.getFileName().toString()))
                            .map(path -> path.resolve("memurai.exe"))
                            .filter(Files::isRegularFile);
                    if (found.isPresent()) {
                        return found.get().toAbsolutePath();
                    }
                } catch (IOException ignored) {
                    // fall through to PATH
                }
            }
        }

        String onPath = findOnPath(WINDOWS ? "memurai.exe" : "redis-server");
        if (onPath != null) {
            return Path.of(onPath).toAbsolutePath();
        }
        onPath = findOnPath("redis-server");
        if (onPath != null) {
            return Path.of(onPath).toAbsolutePath();
        }
        throw new IllegalStateException("未发现 Memurai 或 redis-server 可执行文件（检查 ZHIYI_REDIS_BIN）");
    }

    private static String findOnPath(String executable) {
        String path = System.getenv("PATH");
        if (path == null) {
            return null;
        }
        for (String entry : path.split(java.io.File.pathSeparator)) {
            if (entry.isBlank()) {
                continue;
            }
            Path candidate = Path.of(entry, executable);
            if (Files.isRegularFile(candidate)) {
                return candidate.toString();
            }
        }
        return null;
    }

    private static int freePort() {
        try (ServerSocket socket = new ServerSocket(0)) {
            socket.setReuseAddress(false);
            return socket.getLocalPort();
        } catch (IOException failure) {
            throw new IllegalStateException("BLOCKED_BY_REDIS: 无法分配 loopback 端口", failure);
        }
    }

    private static String tail(Path log) {
        try {
            var lines = Files.readAllLines(log, StandardCharsets.UTF_8);
            int from = Math.max(0, lines.size() - 30);
            return String.join(System.lineSeparator(), lines.subList(from, lines.size()));
        } catch (IOException failure) {
            return "<无法读取日志 " + log + ": " + failure.getMessage() + ">";
        }
    }

    private static void sleepQuietly(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Redis 就绪等待被中断", interrupted);
        }
    }

    private static void deleteRecursively(Path root) {
        if (root == null || !Files.exists(root)) {
            return;
        }
        try (Stream<Path> paths = Files.walk(root)) {
            paths.sorted(Comparator.reverseOrder()).forEach(path -> {
                try {
                    Files.deleteIfExists(path);
                } catch (IOException ignored) {
                    // 尽力清理。
                }
            });
        } catch (IOException ignored) {
            // 同上。
        }
    }
}
