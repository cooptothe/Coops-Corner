package com.thecorner.market;
import java.util.Set;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;
import static org.junit.jupiter.api.Assertions.*;

class LiveStatusTest {
    @Test void strictLeagueFilters() {
        assertEquals(Set.of("nba","nfl"),LiveStatusController.leagues("nba,nfl"));
        assertEquals(Set.of(),LiveStatusController.leagues(null));
        assertThrows(MarketProblem.class,()->LiveStatusController.leagues("nba,*"));
        assertThrows(MarketProblem.class,()->LiveStatusController.leagues("nba,"));
    }
    @Test void expiredFutureAndMismatchedEventsAreNotBroadcast() {
        var json=JsonMapper.builder().build();
        var n=json.readTree("""
          {"format":"corner.live_status/1","production_authorized":false,"game_id":"basketball:nba:1",
           "league":"nba","observed_at_ms":1000,"expires_at_ms":61000}
          """);
        assertTrue(LiveStatusController.valid(n,Set.of("nba"),2000));
        assertFalse(LiveStatusController.valid(n,Set.of("nfl"),2000));
        assertFalse(LiveStatusController.valid(n,Set.of(),61000));
        assertFalse(LiveStatusController.valid(n,Set.of(),999));
    }
}
