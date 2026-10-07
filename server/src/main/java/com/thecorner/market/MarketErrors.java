package com.thecorner.market;

import java.util.Map;
import org.springframework.dao.DataAccessException;
import org.springframework.http.ResponseEntity;
import org.springframework.transaction.TransactionException;
import org.springframework.web.bind.annotation.*;

@RestControllerAdvice
public class MarketErrors {
    static ResponseEntity<?> error(int status,String code,String message) {
        return ResponseEntity.status(status).header("Cache-Control","no-store").body(Map.of("error",Map.of("code",code,"message",message)));
    }
    @ExceptionHandler(MarketProblem.class) ResponseEntity<?> problem(MarketProblem e) { return error(e.status,e.code,e.getMessage()); }
    @ExceptionHandler({org.springframework.http.converter.HttpMessageNotReadableException.class,
        org.springframework.web.method.annotation.MethodArgumentTypeMismatchException.class})
    ResponseEntity<?> malformed(Exception e) { return error(400,"invalid_request","Malformed request."); }
    @ExceptionHandler({DataAccessException.class,TransactionException.class}) ResponseEntity<?> database(Exception e) {
        return error(503,"database_unavailable","The database service is unavailable. Try again shortly.");
    }
    @ExceptionHandler(Exception.class) ResponseEntity<?> unexpected(Exception e) {
        return error(500,"internal_error","Unable to complete the request.");
    }
}
