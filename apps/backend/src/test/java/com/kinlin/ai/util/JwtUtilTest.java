package com.kinlin.ai.util;

import com.kinlin.ai.config.JwtProperties;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.security.SignatureException;
import org.junit.jupiter.api.Test;

import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * JwtUtil 行为冻结测试（J1.4B）。
 *
 * <p>合同：claims(userId/username/role)、subject、expiration、签名算法
 * 全部保持既有行为不变；本轮只把 secret/expiration 的所有权移交
 * typed {@link JwtProperties}。</p>
 */
class JwtUtilTest {

    private static final String SECRET_64_BYTES =
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

    private static JwtProperties properties(String secret, long expirationMs) {
        JwtProperties properties = new JwtProperties();
        properties.setSecret(secret);
        properties.setExpiration(expirationMs);
        return properties;
    }

    @Test
    void validTokenIsAcceptedAndCarriesControlledClaims() {
        JwtUtil jwtUtil = new JwtUtil(properties(SECRET_64_BYTES, 60_000));
        UUID userId = UUID.randomUUID();
        String token = jwtUtil.generateToken(userId, "alice");

        assertEquals("alice", jwtUtil.getUsernameFromToken(token));
        assertEquals(userId, jwtUtil.getUserIdFromToken(token));
        assertEquals("USER", jwtUtil.getRoleFromToken(token));

        Claims claims = jwtUtil.getClaimFromToken(token, c -> c);
        assertEquals("alice", claims.getSubject());
        assertTrue(claims.getExpiration().after(new java.util.Date()));
    }

    @Test
    void expiredTokenIsRejected() {
        JwtUtil jwtUtil = new JwtUtil(properties(SECRET_64_BYTES, -1));
        String token = jwtUtil.generateToken(UUID.randomUUID(), "alice");

        assertThrows(ExpiredJwtException.class, () -> jwtUtil.validateToken(token, "alice"));
    }

    @Test
    void tamperedTokenIsRejected() {
        JwtUtil jwtUtil = new JwtUtil(properties(SECRET_64_BYTES, 60_000));
        String token = jwtUtil.generateToken(UUID.randomUUID(), "alice");

        // 篡改 payload 中段一个字符，签名校验必须失败
        String[] parts = token.split("\\.");
        String payload = parts[1];
        String flipped = payload.charAt(0) == 'a' ? 'b' + payload.substring(1) : 'a' + payload.substring(1);
        String tampered = parts[0] + "." + flipped + "." + parts[2];

        assertThrows(JwtException.class, () -> jwtUtil.getUsernameFromToken(tampered));
    }

    @Test
    void tokenSignedWithDifferentSecretIsRejected() {
        JwtUtil signer = new JwtUtil(properties(SECRET_64_BYTES, 60_000));
        JwtUtil verifier = new JwtUtil(properties(
                "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff", 60_000));
        String token = signer.generateToken(UUID.randomUUID(), "alice");

        assertThrows(SignatureException.class, () -> verifier.getUsernameFromToken(token));
    }

    @Test
    void expirationValueControlsTokenLifetime() {
        long expirationMs = 5_000L;
        JwtUtil jwtUtil = new JwtUtil(properties(SECRET_64_BYTES, expirationMs));
        String token = jwtUtil.generateToken(UUID.randomUUID(), "alice");
        java.util.Date expiration = jwtUtil.getExpirationDateFromToken(token);

        long lifetime = expiration.getTime() - jwtUtil.getClaimFromToken(token, Claims::getIssuedAt).getTime();
        assertTrue(Math.abs(lifetime - expirationMs) <= 1_000,
                "token 生命周期应等于配置的 expiration（±1s 时钟误差）");
    }
}
