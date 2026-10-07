package com.thecorner.market;

import javax.sql.DataSource;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;

@SpringBootApplication
public class MarketApplication {
    public static void main(String[] args) { SpringApplication.run(MarketApplication.class, args); }

    @Bean
    DataSourceTransactionManager transactionManager(DataSource source) {
        var manager = new DataSourceTransactionManager(source);
        manager.setEnforceReadOnly(true); // Sends SET TRANSACTION READ ONLY, not merely a JDBC hint.
        return manager;
    }
}
