package com.thecorner.market;

import java.time.Duration;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.data.redis.core.ScanOptions;
import org.springframework.data.redis.connection.ReactiveRedisConnectionFactory;
import org.springframework.data.redis.listener.ChannelTopic;
import org.springframework.data.redis.listener.ReactiveRedisMessageListenerContainer;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.bind.annotation.*;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.util.retry.Retry;
import reactor.core.scheduler.Schedulers;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import jakarta.annotation.PreDestroy;

/** Public display telemetry only; no account data, wagers or domain authorization. */
@RestController
@RequestMapping("/api/v1/sports")
@ConditionalOnProperty(name="corner.live.enabled",havingValue="true")
public class LiveStatusController {
    private final ReactiveStringRedisTemplate redis;
    private final ReactiveRedisMessageListenerContainer listener;
    private final JsonMapper json = JsonMapper.builder().build();
    private final Flux<Packet> updates;
    private final AtomicInteger clients = new AtomicInteger();
    private final LiveEventMapping mappings;
    record Packet(String channel, String body) {}

    LiveStatusController(ReactiveStringRedisTemplate redis, ReactiveRedisConnectionFactory factory, LiveEventMapping mappings) {
        this.redis=redis;
        this.mappings=mappings;
        listener=new ReactiveRedisMessageListenerContainer(factory);
        // One Redis subscription shared by clients. Disconnection never becomes an empty success.
        updates=listener.receive(new ChannelTopic("sports:live:updates"), new ChannelTopic("sports:live:stoppage_alerts"))
            .map(m->new Packet(m.getChannel(),m.getMessage()))
            .retryWhen(Retry.backoff(3,Duration.ofSeconds(1)).maxBackoff(Duration.ofSeconds(10)))
            .publish().refCount(1);
    }
    @PreDestroy void close() { listener.destroy(); }

    static Set<String> leagues(String value) {
        if(value==null || value.isBlank()) return Set.of();
        String[] parts=value.split(",",-1);
        if(parts.length>32 || Arrays.stream(parts).anyMatch(p->!p.matches("[a-z0-9][a-z0-9.-]{0,63}")))
            throw new MarketProblem(400,"invalid_leagues","Use up to 32 comma-separated league identifiers.");
        return Set.copyOf(Arrays.asList(parts));
    }
    static boolean valid(JsonNode n, Set<String> leagues, long now) {
        return n.isObject() && "corner.live_status/1".equals(n.path("format").asText())
            && n.path("production_authorized").isBoolean() && !n.path("production_authorized").asBoolean()
            && n.path("game_id").isTextual() && n.path("league").isTextual()
            && n.path("observed_at_ms").isIntegralNumber() && n.path("expires_at_ms").isIntegralNumber()
            && n.path("observed_at_ms").asLong()<=now && n.path("expires_at_ms").asLong()>now
            && n.path("expires_at_ms").asLong()-n.path("observed_at_ms").asLong()==60000
            && (leagues.isEmpty() || leagues.contains(n.path("league").asText()));
    }
    private boolean accepted(String body,Set<String> leagues) {
        if(body.length()>16000) return false;
        try { return valid(json.readTree(body),leagues,System.currentTimeMillis()); }
        catch(Exception e) { return false; }
    }
    @GetMapping(value="/live-stream",produces=MediaType.TEXT_EVENT_STREAM_VALUE)
    public ResponseEntity<Flux<ServerSentEvent<String>>> stream(@RequestParam(required=false) String leagues) {
        Set<String> selected=leagues(leagues);
        Flux<ServerSentEvent<String>> stream=Flux.defer(()->{
            if(clients.incrementAndGet()>200) {
                clients.decrementAndGet();
                return Flux.error(new MarketProblem(503,"stream_capacity","Live display connection capacity reached."));
            }
            var messages=updates.filter(p->accepted(p.body(),selected))
                .map(p->ServerSentEvent.<String>builder(p.body()).event(p.channel().endsWith("stoppage_alerts")?"stoppage":"status").build());
            // Pub/Sub has no replay. Re-fetch a snapshot on connect and periodically (also after Redis reconnect).
            var resync=Flux.interval(Duration.ZERO,Duration.ofSeconds(15))
                .map(i->ServerSentEvent.<String>builder("{\"snapshot_required\":true}").event("resync").build());
            return Flux.merge(messages,resync).onBackpressureBuffer(256)
                .take(Duration.ofMinutes(10))
                .doFinally(signal->clients.decrementAndGet());
        });
        return ResponseEntity.ok().header("Cache-Control","no-store").header("X-Accel-Buffering","no").body(stream);
    }
    @GetMapping("/live-snapshot")
    public Mono<ResponseEntity<Map<String,Object>>> snapshot(@RequestParam(required=false) String leagues) {
        Set<String> selected=leagues(leagues);
        return redis.scan(ScanOptions.scanOptions().match("live_game:*").count(200).build())
            .take(5001).collectList().flatMap(keys->{
                if(keys.size()>5000) return Mono.error(new MarketProblem(503,"snapshot_capacity","Snapshot capacity exceeded."));
                return Flux.fromIterable(new HashSet<>(keys))
                    .flatMap(k->redis.<String,String>opsForHash().get(k,"payload"),8)
                    .filter(body->accepted(body,selected)).map(json::readTree).collectList();
            }).flatMap(items->Mono.fromCallable(()->mappings.attach(items)).subscribeOn(Schedulers.boundedElastic()))
            .timeout(Duration.ofSeconds(8))
            .map(items->ResponseEntity.ok().header("Cache-Control","no-store")
                .body(Map.<String,Object>of("items",items,"production_authorized",false,"source","espn_scoreboard")))
            .onErrorMap(e->e instanceof MarketProblem?e:new MarketProblem(503,"live_unavailable","Live cache unavailable; discard stale state."));
    }
}
