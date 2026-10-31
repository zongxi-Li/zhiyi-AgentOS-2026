package com.kinlin.ai.integration;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.Locale;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class NativePostgresTest {
    @TempDir
    Path parent;

    @Test
    void realClusterUsesOwnedSocketAndTcpThenStopsAndDeletesItsFiles() throws Exception {
        // 包含空格/逗号的路径也不能变成多个 GUC socket 目录。
        Path temporaryParent = Files.createDirectory(parent.resolve("owned space,dir"));
        NativePostgres cluster = NativePostgres.start("native_contract", "native_it", "test", temporaryParent);
        Path root;
        long pid;
        String url = cluster.getJdbcUrl();
        try (cluster;
             var connection = DriverManager.getConnection(url, cluster.getUsername(), cluster.getPassword());
             var statement = connection.createStatement()) {
            assertThat(cluster.describe()).startsWith("PostgreSQL 15.");
            assertThat(url).startsWith("jdbc:postgresql://127.0.0.1:");
            try (var row = statement.executeQuery("SHOW data_directory")) {
                assertThat(row.next()).isTrue();
                root = Path.of(row.getString(1)).getParent();
            }
            pid = Long.parseLong(Files.readAllLines(root.resolve("data/postmaster.pid")).get(0));
            try (var row = statement.executeQuery("SHOW unix_socket_directories")) {
                assertThat(row.next()).isTrue();
                if (isWindows()) {
                    assertThat(Files.exists(root.resolve("socket"))).isFalse();
                } else {
                    assertThat(row.getString(1)).contains(root.resolve("socket").toString());
                    assertThat(Files.getPosixFilePermissions(root.resolve("socket")))
                            .isEqualTo(PosixFilePermissions.fromString("rwx------"));
                    assertThat(Files.exists(root.resolve("socket/.s.PGSQL." + cluster.getPort()))).isTrue();
                }
            }
            assertThat(cluster.createDatabase("second_database")).endsWith("/second_database");
        }
        cluster.close(); // 关闭幂等；不重复清理或影响其它实例。
        assertThat(ProcessHandle.of(pid).map(ProcessHandle::isAlive).orElse(false)).isFalse();
        assertThat(root).doesNotExist();
        assertThatThrownBy(() -> DriverManager.getConnection(url, "native_it", "test"))
                .isInstanceOf(SQLException.class);
    }

    @Test
    void failureAfterServerIsReadyStopsOwnedProcessAndRemovesCluster() throws Exception {
        assertThatThrownBy(() -> NativePostgres.start("invalid-name", "native_it", "test", parent))
                .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("Unsafe test database name");
        try (var children = Files.list(parent)) {
            assertThat(children.toList()).isEmpty();
        }
        assertThat(ProcessHandle.current().descendants()
                .filter(p -> p.info().commandLine().orElse("").contains(parent.toString())).toList()).isEmpty();
    }

    @Test
    void majorVersionDriftAndUnknownVersionsFailExplicitly() {
        NativePostgres.requirePostgres15("postgres (PostgreSQL) 15.19");
        NativePostgres.requirePostgres15("15.19 (Ubuntu 15.19-1.pgdg24.04+2)");
        assertThatThrownBy(() -> NativePostgres.requirePostgres15("postgres (PostgreSQL) 18.6"))
                .hasMessageContaining("BLOCKED_BY_PG");
        assertThatThrownBy(() -> NativePostgres.requirePostgres15("unknown"))
                .hasMessageContaining("BLOCKED_BY_PG");
    }

    @Test
    void windowsDoesNotReceiveUnixSocketOption() {
        Path bin = Path.of("binary");
        assertThat(NativePostgres.serverCommand(bin, parent, 32123, true))
                .noneMatch(option -> option.contains("unix_socket"));
        assertThat(NativePostgres.serverCommand(bin, parent, 32123, false))
                .anyMatch(option -> option.startsWith("unix_socket_directories="));
    }

    private static boolean isWindows() {
        return System.getProperty("os.name", "").toLowerCase(Locale.ROOT).contains("win");
    }
}
