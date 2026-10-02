package com.kinlin.ai.projection.output.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.math.BigDecimal;
import java.util.List;

/**
 * The dedicated user-product-body value grammar (phase ruling 4.3): exactly one of
 * the scalar slots is set per {@code kind}, lists keep the upstream element order,
 * object members keep the upstream key order, and there is no length, item-count
 * or depth truncation — product bodies must survive completely.
 *
 * <p>This grammar is approved for output content only (OutputQuery and
 * LegacyOutputItemQuery); the guard verifies it does not spread to any control
 * DTO. Numbers are exact BigDecimals built from the wire text (no float detour),
 * so integers stay integers and decimals round-trip.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ContentValueQuery(
        String kind,
        String text,
        Boolean bool,
        BigDecimal number,
        List<ContentValueQuery> items,
        List<ContentMemberQuery> members
) implements QueryResponse {
}
