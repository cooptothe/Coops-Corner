package com.thecorner.market;

import java.util.*;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/account/v1")
@ConditionalOnProperty(name="corner.accounts.enabled",havingValue="true")
public class PersonalController {
    final PersonalRecords records;
    PersonalController(PersonalRecords records) { this.records=records; }
    static void origin(HttpServletRequest r) {
        if(!Set.of("http://127.0.0.1:3000","http://localhost:3000").contains(Objects.toString(r.getHeader("Origin"),"")) || !"1".equals(r.getHeader("X-Corner-Request")))
            throw new MarketProblem(403,"origin_refused","Use the local Corner app to save records.");
    }
    static ResponseEntity<?> reply(Object data) { return ResponseEntity.ok().header("Cache-Control","no-store").body(data); }
    static String cookie(String token,long age) { return ResponseCookie.from("corner_session",token).httpOnly(true).sameSite("Strict").path("/api/account/v1").maxAge(age).build().toString(); }
    @PostMapping({"/register","/login"}) ResponseEntity<?> login(@RequestBody Map<String,String> input,HttpServletRequest r) {
        origin(r); var result=records.authenticate(input,r.getRequestURI().endsWith("/register"),r.getRemoteAddr());
        return ResponseEntity.ok().header("Cache-Control","no-store").header("Set-Cookie",cookie(result.token(),28800)).body(result.profile());
    }
    @GetMapping("/session") ResponseEntity<?> session(@CookieValue(name="corner_session",required=false) String token) { return reply(records.session(token)); }
    @PostMapping("/logout") ResponseEntity<?> logout(@CookieValue(name="corner_session",required=false) String token,@RequestHeader(name="X-CSRF-Token",required=false) String csrf,HttpServletRequest r) {
        origin(r); records.logout(token,csrf); return ResponseEntity.ok().header("Cache-Control","no-store").header("Set-Cookie",cookie("",0)).body(Map.of("signed_out",true));
    }
    @GetMapping("/records") ResponseEntity<?> list(@CookieValue(name="corner_session",required=false) String token,@RequestParam(defaultValue="0") int offset) {
        var session=records.session(token); return reply(records.dashboard(UUID.fromString((String)session.get("id")),offset));
    }
    @PostMapping({"/records","/cash"}) ResponseEntity<?> save(@CookieValue(name="corner_session",required=false) String token,@RequestHeader(name="X-CSRF-Token",required=false) String csrf,@RequestBody Map<String,String> input,HttpServletRequest r) {
        origin(r); return reply(records.save(records.owner(token,csrf),input,r.getRequestURI().endsWith("/cash")));
    }
}
