package com.thecorner.market;

import java.util.*;
import org.springframework.http.ResponseEntity;
import org.springframework.util.MultiValueMap;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/market/v1")
public class MarketController {
    private final MarketRepository repository;
    public MarketController(MarketRepository repository) { this.repository=repository; }
    private static void validate(MultiValueMap<String,String> query, Set<String> allowed) {
        if(query.entrySet().stream().anyMatch(e->!allowed.contains(e.getKey()) || e.getValue().size()!=1))
            throw new MarketProblem(400,"invalid_query","Unknown or repeated query parameter.");
    }
    static int number(MultiValueMap<String,String> query,String key,int fallback) {
        try { return query.containsKey(key)?Integer.parseInt(query.getFirst(key)):fallback; }
        catch(NumberFormatException e) { throw new MarketProblem(400,"invalid_query","Invalid page bounds."); }
    }
    private ResponseEntity<?> ok(Object body) { return ResponseEntity.ok().header("Cache-Control","no-store").body(body); }
    @GetMapping("/health") public ResponseEntity<?> health() { return ok(repository.health()); }
    @GetMapping("/games") public ResponseEntity<?> games(@RequestParam MultiValueMap<String,String> query) {
        validate(query,Set.of("search","market_key","offset","limit","upcoming"));
        return ok(repository.games(query.getFirst("search")==null?"":query.getFirst("search"),query.getFirst("market_key"),number(query,"offset",0),number(query,"limit",25),"true".equals(query.getFirst("upcoming"))));
    }
    @GetMapping("/games/{id}/odds") public ResponseEntity<?> odds(@PathVariable String id,@RequestParam MultiValueMap<String,String> query) {
        validate(query,Set.of("market_key"));
        UUID event;
        try { event=UUID.fromString(id); } catch(IllegalArgumentException e) { throw new MarketProblem(400,"invalid_id","Game ID must be a UUID."); }
        return ok(repository.board(event,query.getFirst("market_key")));
    }
}
