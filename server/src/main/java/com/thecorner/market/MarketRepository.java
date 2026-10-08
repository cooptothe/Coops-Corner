package com.thecorner.market;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.function.Supplier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

@Repository
public class MarketRepository {
    static final Map<String,String> MARKETS = Map.of("moneyline","h2h", "spread","spreads",
        "total","totals", "outright","outrights", "moneyline_lay","h2h_lay", "outright_lay","outrights_lay");
    static final String FEATURED = """
        mt.code IN ('moneyline','spread','total','outright','moneyline_lay','outright_lay')
        AND m.subject_participant_id IS NULL
        AND scope.code=CASE WHEN mt.code IN ('outright','outright_lay') THEN 'competition' ELSE 'full_game' END
        """;
    static final String MARKET_JOIN = """
        JOIN corner.market_types mt ON mt.id=m.market_type_id
        JOIN corner.scopes scope ON scope.id=m.scope_id
        """;
    private final JdbcTemplate jdbc;
    private final TransactionTemplate read;
    private final long maxAge;
    private final String dataset;
    public MarketRepository(JdbcTemplate jdbc, PlatformTransactionManager manager,
                            @Value("${corner.market.max-age-seconds}") long maxAge,
                            @Value("${corner.market.dataset:retained}") String dataset) {
        if (maxAge < 1 || maxAge > 86400) throw new IllegalArgumentException("Quote age limit must be 1..86400 seconds");
        if (!Set.of("retained","synthetic_acceptance").contains(dataset)) throw new IllegalArgumentException("Unknown dataset label");
        this.jdbc=jdbc; this.maxAge=maxAge;
        this.dataset=dataset;
        jdbc.setQueryTimeout(5);
        read = new TransactionTemplate(manager);
        read.setReadOnly(true);
        read.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
        read.setTimeout(8);
    }
    private Map<String,Object> envelope(Supplier<Map<String,Object>> query) {
        return read.execute(status -> {
            Instant at = jdbc.queryForObject("SELECT transaction_timestamp()", (r,n)->r.getTimestamp(1).toInstant());
            var data = query.get();
            return Map.of("meta", Map.of("format","corner.market_api/1", "data_mode","database",
                "read_at",at.toString(), "production_authorized",false, "availability_verified",false,
                "max_age_seconds",maxAge,"dataset",dataset), "data",data);
        });
    }
    public Map<String,Object> health() {
        return envelope(() -> {
            // Verify the actual query permissions/schema rather than only SELECT 1.
            jdbc.queryForList("SELECT observation_id FROM corner.trusted_current_quotes LIMIT 0");
            jdbc.queryForList("SELECT id FROM corner.events LIMIT 0");
            return Map.of("status","ready", "transaction_read_only", jdbc.queryForObject("SHOW transaction_read_only",String.class));
        });
    }
    static String dbMarket(String key) {
        if (key == null || key.isBlank()) return null;
        for (var entry : MARKETS.entrySet()) {
            if (Objects.equals(entry.getValue(), key)) return entry.getKey();
        }
        throw new MarketProblem(400, "invalid_market", "Unsupported market.");
    }
    public Map<String,Object> games(String search, String market, int offset, int limit, boolean upcoming) {
        if(offset<0 || offset>10000 || limit<1 || limit>100 || search.length()>100)
            throw new MarketProblem(400,"invalid_query","Invalid search or page bounds.");
        String type = dbMarket(market);
        return envelope(() -> {
            var params = new ArrayList<Object>();
            String predicate = """
                EXISTS(SELECT 1 FROM corner.markets m
                """ + MARKET_JOIN + " WHERE m.event_id=e.id AND " + FEATURED
                + (type==null ? "" : " AND mt.code=?") + ")" + (upcoming ? " AND e.scheduled_start > clock_timestamp()" : "");
            if(type!=null) params.add(type);
            if(!search.isBlank()) {
                predicate += " AND (c.display_name ILIKE ? ESCAPE '!' OR EXISTS (SELECT 1 FROM corner.event_participants ep JOIN corner.participants p ON p.id=ep.participant_id WHERE ep.event_id=e.id AND p.display_name ILIKE ? ESCAPE '!'))";
                String pattern = "%"+search.replace("!","!!").replace("%","!%").replace("_","!_")+"%";
                params.add(pattern); params.add(pattern);
            }
            String from = " FROM corner.events e JOIN corner.competitions c ON c.id=e.competition_id WHERE "+predicate;
            long total = jdbc.queryForObject("SELECT count(*)"+from,Long.class,params.toArray());
            params.add(limit); params.add(offset);
            var events = jdbc.queryForList("SELECT e.id::text, e.scheduled_start, c.display_name AS competition, c.code AS competition_code"+from+" ORDER BY e.scheduled_start,e.id LIMIT ? OFFSET ?", params.toArray());
            var items = events.stream().map(this::game).toList();
            var page = new LinkedHashMap<String,Object>();
            page.put("items",items); page.put("total",total); page.put("offset",offset); page.put("limit",limit);
            page.put("next_offset",offset+items.size()<total ? offset+items.size() : null);
            return page;
        });
    }
    private Map<String,Object> game(Map<String,Object> row) {
        String id = (String)row.get("id");
        var participants = jdbc.queryForList("SELECT p.display_name AS name,ep.role FROM corner.event_participants ep JOIN corner.participants p ON p.id=ep.participant_id WHERE ep.event_id=?::uuid ORDER BY ep.role,p.id", id);
        String home=null, away=null;
        for(var p: participants) {
            if("home".equals(p.get("role"))) home=(String)p.get("name");
            if("away".equals(p.get("role"))) away=(String)p.get("name");
        }
        var markets = jdbc.queryForList("SELECT DISTINCT mt.code FROM corner.markets m "+MARKET_JOIN+" WHERE m.event_id=?::uuid AND "+FEATURED+" ORDER BY mt.code",String.class,id).stream().map(MARKETS::get).toList();
        var result=new LinkedHashMap<String,Object>();
        result.put("id",id); result.put("name",home!=null && away!=null ? away+" at "+home : row.get("competition")+" — outright");
        result.put("competition",row.get("competition")); result.put("competition_code",row.get("competition_code"));
        result.put("starts_at",((java.sql.Timestamp)row.get("scheduled_start")).toInstant().toString());
        result.put("participants",participants); result.put("market_keys",markets); result.put("phase","unknown");
        return result;
    }
    public Map<String,Object> board(UUID event, String market) {
        String type = dbMarket(market);
        return envelope(() -> {
            var events = jdbc.queryForList("SELECT e.id::text,e.scheduled_start,c.display_name AS competition,c.code AS competition_code FROM corner.events e JOIN corner.competitions c ON c.id=e.competition_id WHERE e.id=?",event);
            if(events.isEmpty()) throw new MarketProblem(404,"game_not_found","Game does not exist.");
            var books=jdbc.queryForList("""
                SELECT DISTINCT b.id::text,b.display_name AS name FROM corner.sportsbooks b
                JOIN corner.odds_observations obs ON obs.sportsbook_id=b.id
                JOIN corner.outcomes o ON o.id=obs.outcome_id JOIN corner.markets m ON m.id=o.market_id
                """+MARKET_JOIN+" WHERE m.event_id=? AND "+FEATURED+" ORDER BY b.id::text LIMIT 101",event);
            if(books.size()>100) throw new MarketProblem(422,"board_too_large","Event exceeds 100 books.");
            var args=new ArrayList<Object>(); args.add(event);
            if(type!=null) args.add(type);
            var outcomes=jdbc.queryForList("""
                SELECT o.id::text,o.market_id::text,o.selected_participant_id::text,side.code AS side,o.point,
                       p.display_name AS participant,mt.code AS market_type,scope.code AS scope
                FROM corner.outcomes o JOIN corner.markets m ON m.id=o.market_id
                JOIN corner.outcome_sides side ON side.id=o.outcome_side_id
                LEFT JOIN corner.participants p ON p.id=o.selected_participant_id
                """+MARKET_JOIN+" WHERE m.event_id=? AND "+FEATURED+(type==null?"":" AND mt.code=?")+" ORDER BY m.id,o.id LIMIT 1001",args.toArray());
            if(outcomes.size()>1000 || (long)outcomes.size()*books.size()>10000)
                throw new MarketProblem(422,"board_too_large","Narrow the market filter to load this board.");
            var quotes=jdbc.queryForList("""
                SELECT t.outcome_id::text,t.sportsbook_id::text,t.observation_id::text,t.provider_payload_id::text,
                       t.provider_id::text,pr.code AS provider,t.latest_disposition_id::text,t.latest_disposition_code,
                       t.decimal_odds,t.observed_at,t.provider_updated_at,qs.code AS state,obs.source_record_key
                FROM corner.trusted_current_quotes t JOIN corner.outcomes o ON o.id=t.outcome_id
                JOIN corner.markets m ON m.id=o.market_id JOIN corner.quote_states qs ON qs.id=t.quote_state_id
                JOIN corner.providers pr ON pr.id=t.provider_id
                JOIN corner.odds_observations obs ON obs.id=t.observation_id
                """+MARKET_JOIN+" WHERE m.event_id=? AND "+FEATURED+(type==null?"":" AND mt.code=?")+" ORDER BY o.id,t.sportsbook_id LIMIT 10001", args.toArray());
            if(quotes.size()>10000) throw new MarketProblem(422,"board_too_large","Narrow the market filter to load this board.");
            Instant at=jdbc.queryForObject("SELECT transaction_timestamp()",(r,n)->r.getTimestamp(1).toInstant());
            var lookup=new HashMap<String,Map<String,Object>>();
            quotes.forEach(q->lookup.put(q.get("outcome_id")+":"+q.get("sportsbook_id"),q));
            var cells=new ArrayList<Map<String,Object>>();
            for(var o: outcomes) for(var b:books) {
                var q=lookup.get(o.get("id")+":"+b.get("id"));
                var cell=new LinkedHashMap<String,Object>();
                cell.put("outcome_id",o.get("id")); cell.put("sportsbook_id",b.get("id"));
                if(q!=null) q.forEach((k,v)->cell.put(k,wire(v)));
                else { cell.put("state","missing"); cell.put("decimal_odds",null); cell.put("observation_id",null); }
                cell.put("display_status",q==null ? "missing" : freshness((String)q.get("state"),instant(q.get("observed_at")),instant(q.get("provider_updated_at")),at,maxAge));
                cells.add(cell);
            }
            var selections=new ArrayList<Map<String,Object>>();
            for(var o:outcomes) {
                var selection=new LinkedHashMap<String,Object>();
                o.forEach((k,v)->selection.put(k,wire(v)));
                selection.put("market_key",MARKETS.get(o.get("market_type")));
                selection.put("selection_name",o.get("participant")!=null ? o.get("participant") : o.get("side"));
                selections.add(selection);
            }
            var result=new LinkedHashMap<String,Object>();
            result.put("game",game(events.getFirst())); result.put("books",books);
            result.put("selections",selections); result.put("quotes",cells);
            result.put("book_universe","books_with_retained_featured_observations_for_event");
            result.put("revision",digest(result.toString()));
            return result;
        });
    }
    static Instant instant(Object value) { return value==null ? null : ((java.sql.Timestamp)value).toInstant(); }
    static Object wire(Object value) {
        if(value instanceof BigDecimal decimal) return decimal.toPlainString();
        if(value instanceof java.sql.Timestamp timestamp) return timestamp.toInstant().toString();
        return value;
    }
    static String freshness(String state, Instant observed, Instant updated, Instant at, long maxAge) {
        if(!"active".equals(state)) return state;
        if(observed==null) return "missing";
        if(observed.isAfter(at) || (updated!=null && updated.isAfter(observed))) return "invalid_timestamp";
        return Duration.between(observed,at).compareTo(Duration.ofSeconds(maxAge))>0 ? "stale" : "fresh";
    }
    static String digest(String content) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(content.getBytes(StandardCharsets.UTF_8))); }
        catch(java.security.NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
    }
}
