package com.kinlin.ai.config;

import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.info.Contact;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Swagger API文档配置
 */
@Configuration
public class SwaggerConfig {

    @Bean
    public OpenAPI customOpenAPI() {
        return new OpenAPI()
                .info(new Info()
                        .title("知弈 API")
                        .version("1.0.0")
                        .description("知弈 - 职业智能体操作系统 API文档")
                        .contact(new Contact()
                                .name("知弈 Team")
                                .email("support@kinlin.ai")));
    }
}

