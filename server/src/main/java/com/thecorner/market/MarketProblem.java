package com.thecorner.market;

final class MarketProblem extends RuntimeException {
    final int status;
    final String code;
    MarketProblem(int status, String code, String message) { super(message); this.status = status; this.code = code; }
}
