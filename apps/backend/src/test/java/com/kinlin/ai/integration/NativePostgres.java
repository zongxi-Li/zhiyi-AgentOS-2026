package com.kinlin.ai.integration;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.net.ServerSocket;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.Properties;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/**
 * 测试自管的真实 PostgreSQL 临时实例（零容器化测试基座）。
 *
 * <p>定位本机 PostgreSQL 15.x 二进制（{@code ZHIYI_PG_BIN} → 本机 ZhiyiNative
 * 依赖包 → CI apt 的 {@code /usr/lib/postgresql/<ver>/bin}）后，在临时目录
 * {@code initdb} 一个一次性 cluster，随机 loopback 端口启动，建库并由
 * JVM shutdown hook 优雅停止、清理临时目录。</p>
 *
 * <p>与容器方案的语义差异只在于生命周期归属：实例由测试 JVM 自己 spawn 和
 * 停止，不依赖容器运行时；连接串、Flyway/Hibernate 校验与真实 SQL 行为
 * 完全一致。二进制/启动失败是显式失败（BLOCKED_BY_PG），不是静默 skip。</p>
 */
public final class NativePostgres implements AutoCloseable {

    private static final boolean WINDOWS =
            System.getProperty("os.name", "").toLowerCase(Locale.ROOT).contains("win");
    private static final Pattern SAFE_DATABASE = Pattern.compile("[A-Za-z0-9_]{1,63}");
    private static final int STARTUP_TIMEOUT_SECONDS = 90;

    private final Path bin;
    private final Path root;
    private final int port;
    private final String username;
    private final String password;
    private final String database;
    private final Process process;
    private final Path serverLog;
    private volatile boolean closed;
    private volatile String serverVersion;

    private NativePostgres(Path bin, Path root, int port, String username, String password,
                           String database, Process process) {
        this.bin = bin;
        this.root = root;
        this.port = port;
        this.username = username;
        this.password = password;
        this.database = database;
        this.process = process;
        this.serverLog = root.resolve("postgres.log");
    }

    public static NativePostgres start(String database, String username, String password) {
        Path bin;
        try {
            bin = locateBin();
        } catch (RuntimeException failure) {
            throw new IllegalStateException(
                    "BLOCKED_BY_PG: 找不到 PostgreSQL 15.x 本机二进制（测试自管临时实例）。"
                            + "设置 ZHIYI_PG_BIN 指向 bin 目录，或运行 prepare_persistent_dependencies.py / "
                            + "在 CI 安装 postgresql。原因: " + failure.getMessage(),
                    failure);
        }
        Path root;
        try {
            root = Files.createTempDirectory("kinlin-pg-it-");
        } catch (IOException failure) {
            throw new IllegalStateException("BLOCKED_BY_PG: 无法创建 PostgreSQL 临时目录", failure);
        }
        int port = freePort();
        NativePostgres instance = null;
        try {
            initdb(bin, root, username);
            Process process = startServer(bin, root, port);
            instance = new NativePostgres(bin, root, port, username, password, database, process);
            instance.awaitReady();
            instance.createDatabase(database);
            Runtime.getRuntime().addShutdownHook(
                    new Thread(instance::closeQuietly, "native-pg-test-cluster-stop"));
            return instance;
        } catch (IOException failure) {
            if (instance != null) {
                instance.close();
            }
            deleteRecursively(root);
            throw new IllegalStateException("BLOCKED_BY_PG: PostgreSQL 临时实例启动失败: "
                    + failure.getMessage(), failure);
        } catch (RuntimeException failure) {
            if (instance != null) {
                instance.close();
            }
            deleteRecursively(root);
            throw failure;
        }
    }

    /** 当前 cluster 的 JDBC URL（指向给定 database）。 */
    public String jdbcUrl(String database) {
        return "jdbc:postgresql://127.0.0.1:" + port + "/" + database;
    }

    public String getJdbcUrl() {
        return jdbcUrl(database);
    }

    public String getUsername() {
        return username;
    }

    public String getPassword() {
        return password;
    }

    public int getPort() {
        return port;
    }

    /** 在同一实例上新建一个全新空库（迁移重放测试的 fresh 语义）。 */
    public String createDatabase(String database) {
        if (!SAFE_DATABASE.matcher(database).matches()) {
            throw new IllegalArgumentException("Unsafe test database name: " + database);
        }
        try (Connection connection = DriverManager.getConnection(jdbcUrl("postgres"), username, password);
             Statement statement = connection.createStatement()) {
            statement.executeUpdate("CREATE DATABASE \"" + database + "\"");
        } catch (SQLException failure) {
            throw new IllegalStateException("BLOCKED_BY_PG: 创建测试库失败: " + database, failure);
        }
        return jdbcUrl(database);
    }

    /** 版本口径：15.x 真实例（不再声称某个容器 tag）。 */
    public String describe() {
        String version = serverVersion;
        if (version == null) {
            version = queryPostgresVersion();
            serverVersion = version;
        }
        return "PostgreSQL " + version + " (native test cluster, port " + port + ")";
    }

    @Override
    public synchronized void close() {
        if (closed) {
            return;
        }
        closed = true;
        stopServer();
        deleteRecursively(root);
    }

    private void closeQuietly() {
        try {
            close();
        } catch (RuntimeException ignored) {
            // JVM 退出路径不因清理失败而改变退出码；日志已落盘。
        }
    }

    private void awaitReady() {
        long deadline = System.nanoTime() + STARTUP_TIMEOUT_SECONDS * 1_000_000_000L;
        Properties properties = new Properties();
        properties.setProperty("user", username);
        properties.setProperty("password", password);
        properties.setProperty("connectTimeout", "1");
        properties.setProperty("loginTimeout", "1");
        while (System.nanoTime() < deadline) {
            if (!process.isAlive()) {
                throw new IllegalStateException("BLOCKED_BY_PG: postgres 进程提前退出。\n" + tail(root.resolve("postgres.log")));
            }
            try (Connection ignored = DriverManager.getConnection(jdbcUrl("postgres"), properties)) {
                return;
            } catch (SQLException notReady) {
                sleepQuietly(200);
            }
        }
        throw new IllegalStateException("BLOCKED_BY_PG: PostgreSQL 临时实例 %ds 内未就绪。\n%s"
                .formatted(STARTUP_TIMEOUT_SECONDS, tail(root.resolve("postgres.log"))));
    }

    private String queryPostgresVersion() {
        try (Connection connection = DriverManager.getConnection(jdbcUrl("postgres"), username, password);
             Statement statement = connection.createStatement();
             ResultSet result = statement.executeQuery("SHOW server_version")) {
            return result.next() ? result.getString(1) : "15.x";
        } catch (SQLException failure) {
            return "15.x";
        }
    }

    private void stopServer() {
        Path pgCtl = executable(bin, "pg_ctl");
        try {
            Process stop = new ProcessBuilder(pgCtl.toString(), "-D", root.resolve("data").toString(),
                    "stop", "-m", "fast", "-w", "-t", "30")
                    .redirectErrorStream(true)
                    .redirectOutput(root.resolve("stop.log").toFile())
                    .start();
            stop.waitFor();
        } catch (IOException | InterruptedException ignored) {
            if (ignored instanceof InterruptedException) {
                Thread.currentThread().interrupt();
            }
        }
        try {
            if (!process.waitFor(15, java.util.concurrent.TimeUnit.SECONDS)) {
                process.destroy();
                if (!process.waitFor(10, java.util.concurrent.TimeUnit.SECONDS)) {
                    process.destroyForcibly();
                }
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            process.destroyForcibly();
        }
    }

    private static void initdb(Path bin, Path root, String username) throws IOException {
        Path data = root.resolve("data");
        Path log = root.resolve("initdb.log");
        List<String> command = new ArrayList<>(List.of(
                executable(bin, "initdb").toString(),
                "-D", data.toString(),
                "-U", username,
                "--auth=trust",
                "--encoding=UTF8",
                "--locale=C",
                "--no-sync"));
        Process initdb = new ProcessBuilder(command)
                .redirectErrorStream(true)
                .redirectOutput(log.toFile())
                .start();
        try {
            if (initdb.waitFor() != 0) {
                throw new IOException("initdb 退出码 " + initdb.exitValue() + "。\n" + tail(log));
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new IOException("initdb 被中断", interrupted);
        }
    }

    private static Process startServer(Path bin, Path root, int port) throws IOException {
        List<String> command = List.of(
                executable(bin, "postgres").toString(),
                "-D", root.resolve("data").toString(),
                "-p", Integer.toString(port),
                "-c", "listen_addresses=127.0.0.1",
                "-c", "fsync=off",
                "-c", "synchronous_commit=off",
                "-c", "full_page_writes=off");
        return new ProcessBuilder(command)
                .redirectErrorStream(true)
                .redirectOutput(root.resolve("postgres.log").toFile())
                .start();
    }

    /**
     * 定位 PostgreSQL bin：env → ZhiyiNative 依赖包 → CI apt 布局 → PATH。
     * 只接受同时含 initdb/postgres/pg_ctl 的目录。
     */
    static Path locateBin() {
        String configured = System.getenv("ZHIYI_PG_BIN");
        if (configured != null && !configured.isBlank()) {
            Path candidate = Path.of(configured);
            if (Files.isRegularFile(candidate)) {
                candidate = candidate.getParent();
            }
            if (isUsableBin(candidate)) {
                return candidate.toAbsolutePath();
            }
            throw new IllegalStateException("ZHIYI_PG_BIN 不是可用的 PostgreSQL bin 目录: " + configured);
        }

        String localAppData = System.getenv("LOCALAPPDATA");
        if (WINDOWS && localAppData != null && !localAppData.isBlank()) {
            Path dependencies = Path.of(localAppData, "ZhiyiNative", "dependencies");
            Path found = newestChild(dependencies, "postgresql-").map(path -> path.resolve("pgsql").resolve("bin"))
                    .filter(NativePostgres::isUsableBin).orElse(null);
            if (found != null) {
                return found.toAbsolutePath();
            }
        }

        Path aptRoot = Path.of("/usr/lib/postgresql");
        if (Files.isDirectory(aptRoot)) {
            try (Stream<Path> versions = Files.list(aptRoot)) {
                Optional<Path> found = versions.filter(Files::isDirectory)
                        .sorted(Comparator.comparing((Path path) -> path.getFileName().toString()).reversed())
                        .map(path -> path.resolve("bin"))
                        .filter(NativePostgres::isUsableBin)
                        .findFirst();
                if (found.isPresent()) {
                    return found.get().toAbsolutePath();
                }
            } catch (IOException ignored) {
                // fall through to PATH
            }
        }

        Path onPath = findOnPath(executableName("postgres"));
        if (onPath != null && isUsableBin(onPath.getParent())) {
            return onPath.getParent().toAbsolutePath();
        }
        throw new IllegalStateException("未发现 PostgreSQL bin 目录（检查 ZHIYI_PG_BIN 或安装 postgresql）");
    }

    private static Optional<Path> newestChild(Path directory, String prefix) {
        if (!Files.isDirectory(directory)) {
            return Optional.empty();
        }
        try (Stream<Path> children = Files.list(directory)) {
            return children.filter(Files::isDirectory)
                    .filter(path -> path.getFileName().toString().startsWith(prefix))
                    .max(Comparator.comparing(path -> path.getFileName().toString()));
        } catch (IOException failure) {
            throw new UncheckedIOException(failure);
        }
    }

    private static boolean isUsableBin(Path candidate) {
        return candidate != null && Files.isDirectory(candidate)
                && Files.isRegularFile(executable(candidate, "initdb"))
                && Files.isRegularFile(executable(candidate, "postgres"))
                && Files.isRegularFile(executable(candidate, "pg_ctl"));
    }

    private static Path findOnPath(String executable) {
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
                return candidate;
            }
        }
        return null;
    }

    private static Path executable(Path bin, String name) {
        return bin.resolve(executableName(name));
    }

    private static String executableName(String name) {
        return WINDOWS ? name + ".exe" : name;
    }

    private static int freePort() {
        try (ServerSocket socket = new ServerSocket(0)) {
            socket.setReuseAddress(false);
            return socket.getLocalPort();
        } catch (IOException failure) {
            throw new IllegalStateException("BLOCKED_BY_PG: 无法分配 loopback 端口", failure);
        }
    }

    private static String tail(Path log) {
        try {
            List<String> lines = Files.readAllLines(log, StandardCharsets.UTF_8);
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
            throw new IllegalStateException("PostgreSQL 就绪等待被中断", interrupted);
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
                    // 尽力清理；临时目录残留不影响测试结论。
                }
            });
        } catch (IOException ignored) {
            // 同上。
        }
    }
}
