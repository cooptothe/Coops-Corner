package com.thecorner.market;

import java.math.BigDecimal;
import java.time.Instant;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class MarketRepositoryTest {
    final Instant at=Instant.parse("2026-10-03T12:00:00Z");
    @Test void exactAgeBoundaryAndFutureTimes() {
        assertEquals("fresh",MarketRepository.freshness("active",at.minusSeconds(120),null,at,120));
        assertEquals("stale",MarketRepository.freshness("active",at.minusSeconds(120).minusNanos(1),null,at,120));
        assertEquals("invalid_timestamp",MarketRepository.freshness("active",at.plusSeconds(1),null,at,120));
        assertEquals("invalid_timestamp",MarketRepository.freshness("active",at,at.plusSeconds(1),at,120));
    }
    @Test void suspensionCannotBecomeFreshOrFallBack() {
        assertEquals("suspended",MarketRepository.freshness("suspended",at.minusSeconds(900),null,at,120));
        assertEquals("missing",MarketRepository.freshness("active",null,null,at,120));
    }
    @Test void decimalPrecisionAndMarketDirectionsPreserved() {
        assertEquals("2.123456",MarketRepository.wire(new BigDecimal("2.123456")));
        assertEquals("moneyline_lay",MarketRepository.dbMarket("h2h_lay"));
        assertEquals("moneyline",MarketRepository.dbMarket("h2h"));
        assertThrows(MarketProblem.class,()->MarketRepository.dbMarket("player_points"));
    }
}
