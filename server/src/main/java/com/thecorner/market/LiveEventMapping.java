package com.thecorner.market;
import java.util.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/** Explicit master identity lookup only: never fuzzy-match names or start times. */
@Component
@ConditionalOnProperty(name="corner.live.enabled",havingValue="true")
class LiveEventMapping {
    final JdbcTemplate jdbc;
    final TransactionTemplate read;
    LiveEventMapping(JdbcTemplate jdbc, PlatformTransactionManager manager) {
        this.jdbc=jdbc; read=new TransactionTemplate(manager); read.setReadOnly(true); read.setTimeout(5);
    }
    List<JsonNode> attach(List<JsonNode> states) {
        if(states.isEmpty()) return states;
        return read.execute(tx->{
            String placeholders=String.join(",",Collections.nCopies(states.size(),"?"));
            var rows=jdbc.queryForList("SELECT i.external_id,i.event_id::text FROM corner.event_provider_identities i JOIN corner.providers p ON p.id=i.provider_id WHERE p.code='espn' AND i.active AND i.external_id IN ("+placeholders+")",states.stream().map(n->n.path("game_id").asString()).toArray());
            var ids=new HashMap<String,String>();
            rows.forEach(r->ids.put((String)r.get("external_id"),(String)r.get("event_id")));
            for(JsonNode state:states) {
                String id=ids.get(state.path("game_id").asString());
                var object=(ObjectNode)state;
                if(id==null) object.putNull("canonical_event_id"); else object.put("canonical_event_id",id);
            }
            return states;
        });
    }
}
