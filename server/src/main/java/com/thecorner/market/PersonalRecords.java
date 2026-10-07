package com.thecorner.market;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.time.Instant;
import java.sql.Timestamp;
import java.util.*;
import java.util.function.Supplier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

@Service
@ConditionalOnProperty(name="corner.accounts.enabled",havingValue="true")
public class PersonalRecords {
    final JdbcTemplate db;
    final TransactionTemplate tx;
    final BCryptPasswordEncoder passwords = new BCryptPasswordEncoder(12);
    final String dummyHash = passwords.encode(UUID.randomUUID().toString());
    static final SecureRandom RANDOM = new SecureRandom();
    PersonalRecords(@Value("${corner.accounts.url}") String url,
                    @Value("${corner.accounts.user}") String user,
                    @Value("${corner.accounts.password}") String password) {
        var source=new DriverManagerDataSource(url,user,password);
        db=new JdbcTemplate(source); db.setQueryTimeout(5);
        tx=new TransactionTemplate(new DataSourceTransactionManager(source)); tx.setTimeout(8);
    }
    <T> T atomic(Supplier<T> action) { return tx.execute(s->action.get()); }
    static String random() { byte[] bytes=new byte[32]; RANDOM.nextBytes(bytes); return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes); }
    static MarketProblem invalid(String message) { return new MarketProblem(400,"invalid_record",message); }
    static String text(Map<String,String> input,String field,int max) {
        String value=input.get(field);
        if(value==null || value.isBlank() || value.length()>max) throw invalid("Invalid "+field+".");
        return value.trim();
    }
    static UUID uuid(String value) {
        try { return UUID.fromString(value); } catch(Exception e) { throw invalid("Invalid record key."); }
    }
    static BigDecimal amount(Map<String,String> input,String field,boolean zero) {
        String value=text(input,field,20);
        if(!value.matches("[0-9]{1,9}(\\.[0-9]{1,2})?")) throw invalid(field+" must be a USD decimal with at most two cents digits.");
        BigDecimal n=new BigDecimal(value);
        if(n.compareTo(new BigDecimal("100000000"))>0 || (zero?n.signum()<0:n.signum()<=0)) throw invalid("Invalid "+field+".");
        return n.setScale(2);
    }
    static Timestamp past(Map<String,String> input,String field) {
        try { var at=Instant.parse(text(input,field,40));
            if(at.isAfter(Instant.now()) || at.isBefore(Instant.parse("1970-01-01T00:00:00Z"))) throw invalid("Dates must describe past activity.");
            return Timestamp.from(at.truncatedTo(java.time.temporal.ChronoUnit.MICROS));
        } catch(MarketProblem e) { throw e; } catch(Exception e) { throw invalid("Invalid "+field+"."); }
    }
    void throttle(String bucket) {
        int count=atomic(()->db.queryForObject("""
            INSERT INTO corner_app.auth_limits(bucket,window_start,attempts) VALUES (?,clock_timestamp(),1)
            ON CONFLICT(bucket) DO UPDATE SET
              attempts=CASE WHEN corner_app.auth_limits.window_start < clock_timestamp()-interval '15 minutes' THEN 1 ELSE corner_app.auth_limits.attempts+1 END,
              window_start=CASE WHEN corner_app.auth_limits.window_start < clock_timestamp()-interval '15 minutes' THEN clock_timestamp() ELSE corner_app.auth_limits.window_start END
            RETURNING attempts
            """,Integer.class,bucket));
        if(count>20) throw new MarketProblem(429,"rate_limited","Too many authentication attempts. Try again in 15 minutes.");
    }
    record Login(String token,Map<String,Object> profile) {}
    Login authenticate(Map<String,String> input,boolean register,String remote) {
        String username=text(input,"username",40).toLowerCase(Locale.ROOT);
        if(!username.matches("[a-z0-9_]{3,40}")) throw invalid("Use 3–40 letters, numbers or underscores for username.");
        String password=input.get("password");
        if(password==null || password.length()<12 || password.getBytes(StandardCharsets.UTF_8).length>72)
            throw invalid("Password must be at least 12 characters and at most 72 UTF-8 bytes.");
        throttle("remote:"+MarketRepository.digest(remote)); throttle("user:"+username);
        String hash=register?passwords.encode(password):null;
        return atomic(()->{
            UUID id;
            if(register) {
                id=UUID.randomUUID();
                int inserted=db.update("INSERT INTO corner_app.users(id,username,password_hash) VALUES (?,?,?) ON CONFLICT(username) DO NOTHING",id,username,hash);
                if(inserted==0) throw new MarketProblem(409,"account_unavailable","That account name is unavailable.");
            } else {
                var rows=db.queryForList("SELECT id,password_hash FROM corner_app.users WHERE username=?",username);
                boolean valid=passwords.matches(password,rows.isEmpty()?dummyHash:(String)rows.getFirst().get("password_hash"));
                if(!valid || rows.isEmpty()) throw new MarketProblem(401,"invalid_credentials","Invalid username or password.");
                id=(UUID)rows.getFirst().get("id");
            }
            String token=random(),csrf=random();
            db.update("DELETE FROM corner_app.sessions WHERE user_id=? AND expires_at<=clock_timestamp()",id);
            db.update("INSERT INTO corner_app.sessions(token_hash,user_id,csrf_token,expires_at) VALUES (?,?,?,clock_timestamp()+interval '8 hours')",MarketRepository.digest(token),id,csrf);
            return new Login(token,Map.of("id",id.toString(),"username",username,"csrf_token",csrf));
        });
    }
    Map<String,Object> session(String token) {
        if(token==null || !token.matches("[A-Za-z0-9_-]{43}")) throw new MarketProblem(401,"sign_in_required","Sign in to view your records.");
        var rows=db.queryForList("""
            SELECT u.id::text,u.username,s.csrf_token FROM corner_app.sessions s
            JOIN corner_app.users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>clock_timestamp()
            """,MarketRepository.digest(token));
        if(rows.isEmpty()) throw new MarketProblem(401,"sign_in_required","Your session has expired. Sign in again.");
        return rows.getFirst();
    }
    UUID owner(String token,String csrf) {
        var s=session(token);
        if(csrf==null || !java.security.MessageDigest.isEqual(csrf.getBytes(StandardCharsets.UTF_8),((String)s.get("csrf_token")).getBytes(StandardCharsets.UTF_8)))
            throw new MarketProblem(403,"csrf_failed","Refresh your session before saving.");
        return UUID.fromString((String)s.get("id"));
    }
    void logout(String token,String csrf) { owner(token,csrf); db.update("DELETE FROM corner_app.sessions WHERE token_hash=?",MarketRepository.digest(token)); }
    Map<String,Object> dashboard(UUID user,int offset) {
        if(offset<0 || offset>100000) throw invalid("Invalid offset.");
        return atomic(()->{
            // Serialize with personal writes so totals and page describe the same record state.
            db.queryForObject("SELECT id FROM corner_app.users WHERE id=? FOR UPDATE",UUID.class,user);
            var totals=db.queryForMap("""
                SELECT count(*) AS record_count,coalesce(sum(stake),0) AS total_staked,
                coalesce(sum(returned),0) AS total_returned,coalesce(sum(returned-stake),0) AS net_profit
                FROM corner_app.settled_records WHERE user_id=?
                """,user);
            var cash=db.queryForMap("""
                SELECT coalesce(sum(CASE WHEN kind='deposit' THEN amount ELSE 0 END),0) AS deposits,
                coalesce(sum(CASE WHEN kind='withdrawal' THEN amount ELSE 0 END),0) AS withdrawals
                FROM corner_app.cash_entries WHERE user_id=?
                """,user);
            totals.putAll(cash);
            totals.put("recorded_balance",((BigDecimal)cash.get("deposits")).subtract((BigDecimal)cash.get("withdrawals")).add((BigDecimal)totals.get("net_profit")));
            var records=db.queryForList("SELECT id::text,description,sportsbook,stake,returned,decimal_odds,placed_at,settled_at FROM corner_app.settled_records WHERE user_id=? ORDER BY settled_at DESC,id LIMIT 50 OFFSET ?",user,offset);
            var entries=db.queryForList("SELECT id::text,kind,amount,note,occurred_at FROM corner_app.cash_entries WHERE user_id=? ORDER BY occurred_at DESC,id LIMIT 50 OFFSET ?",user,offset);
            return Map.of("summary",wire(totals),"records",records.stream().map(PersonalRecords::wire).toList(),"cash_entries",entries.stream().map(PersonalRecords::wire).toList(),"offset",offset,"limit",50,"currency","USD","mode","manual_retrospective");
        });
    }
    static Map<String,Object> wire(Map<String,Object> input) {
        var output=new LinkedHashMap<String,Object>(); input.forEach((k,v)->output.put(k,MarketRepository.wire(v))); return output;
    }
    Map<String,Object> save(UUID user,Map<String,String> input,boolean cash) {
        UUID key=uuid(input.get("request_key"));
        var values=new LinkedHashMap<String,Object>();
        if(cash) {
            String kind=text(input,"kind",12);
            if(!Set.of("deposit","withdrawal").contains(kind)) throw invalid("Unsupported cash entry type.");
            values.put("kind",kind); values.put("amount",amount(input,"amount",false));
            String note=input.getOrDefault("note","").trim(); if(note.length()>300) throw invalid("Note is too long.");
            values.put("note",note); values.put("occurred_at",past(input,"occurred_at"));
        } else {
            values.put("description",text(input,"description",300)); values.put("sportsbook",text(input,"sportsbook",100));
            values.put("stake",amount(input,"stake",false)); values.put("returned",amount(input,"returned",true));
            String raw=text(input,"decimal_odds",20);
            if(!raw.matches("[0-9]{1,7}(\\.[0-9]{1,8})?")) throw invalid("Invalid decimal odds.");
            var odds=new BigDecimal(raw);
            if(odds.compareTo(BigDecimal.ONE)<=0 || odds.compareTo(new BigDecimal("1000000"))>0) throw invalid("Invalid decimal odds.");
            values.put("decimal_odds",odds.setScale(8));
            var placed=past(input,"placed_at"); var settled=past(input,"settled_at");
            if(settled.before(placed)) throw invalid("Settlement cannot precede placement.");
            values.put("placed_at",placed); values.put("settled_at",settled);
        }
        return atomic(()->{
            db.queryForObject("SELECT id FROM corner_app.users WHERE id=? FOR UPDATE",UUID.class,user);
            String table=cash?"cash_entries":"settled_records";
            var prior=db.queryForList("SELECT * FROM corner_app."+table+" WHERE user_id=? AND request_key=?",user,key);
            if(!prior.isEmpty()) {
                var old=prior.getFirst();
                if(values.entrySet().stream().anyMatch(e->!e.getValue().equals(old.get(e.getKey()))))
                    throw new MarketProblem(409,"idempotency_conflict","This save key already belongs to a different record.");
                return Map.of("id",old.get("id").toString(),"reused",true);
            }
            UUID id=UUID.randomUUID();
            var args=new ArrayList<Object>(List.of(id,user,key)); args.addAll(values.values());
            db.update("INSERT INTO corner_app."+table+"(id,user_id,request_key,"+String.join(",",values.keySet())+") VALUES ("+String.join(",",Collections.nCopies(args.size(),"?"))+")",args.toArray());
            return Map.of("id",id.toString(),"reused",false);
        });
    }
}
