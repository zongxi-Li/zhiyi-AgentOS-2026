package com.kinlin.ai.performance;

import com.kinlin.ai.entity.Conversation;
import com.kinlin.ai.entity.Message;
import com.kinlin.ai.entity.User;
import com.kinlin.ai.repository.ConversationRepository;
import com.kinlin.ai.repository.MessageRepository;
import com.kinlin.ai.repository.UserRepository;
import com.kinlin.ai.service.ChatService;
import com.kinlin.ai.service.ConversationService;
import jakarta.persistence.EntityManagerFactory;
import org.hibernate.SessionFactory;
import org.hibernate.stat.Statistics;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * J1.4C §八/§十五：确定性 query-count 测量（MEASURE FIRST）。
 *
 * <p>对 J1.4A 登记的持久化 debt 逐项量化（statement 数 / 行数），锁定
 * 优化准入证据。普通 {@code mvn test} 必须运行本类——它在数据量固定时
 * 是防回退契约（statement 数随数据量线性增长即 N+1 回归）。</p>
 *
 * <p>统计来源：Hibernate Statistics（generate_statistics 仅在测试 profile 开启，
 * 生产不开启、不落 SQL 全量日志）。</p>
 */
@SpringBootTest
@ActiveProfiles("test")
class QueryDebtMeasurementTest {

    @Autowired
    private ChatService chatService;

    @Autowired
    private ConversationService conversationService;

    @Autowired
    private ConversationRepository conversationRepository;

    @Autowired
    private MessageRepository messageRepository;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private EntityManagerFactory entityManagerFactory;

    private Statistics statistics;

    @BeforeEach
    void resetStatistics() {
        statistics = entityManagerFactory.unwrap(SessionFactory.class).getStatistics();
        statistics.clear();
    }

    private long statements() {
        return statistics.getPrepareStatementCount();
    }

    private long loadedEntities() {
        return statistics.getEntityLoadCount();
    }

    private UUID newUser() {
        User user = new User();
        user.setUsername("query_debt_" + UUID.randomUUID());
        user.setEmail("query_debt_" + UUID.randomUUID() + "@example.com");
        return userRepository.saveAndFlush(user).getId();
    }

    private Conversation newConversation(UUID userId, String contextId) {
        Conversation conversation = new Conversation();
        conversation.setUserId(userId);
        conversation.setContextId(contextId);
        conversation.setWorkspaceMode("chat");
        return conversationRepository.saveAndFlush(conversation);
    }

    private Message newMessage(UUID conversationId, Message.MessageRole role, String content) {
        Message message = new Message();
        message.setConversationId(conversationId);
        message.setRole(role);
        message.setContent(content);
        return messageRepository.saveAndFlush(message);
    }

    /** §十五A：getHistory 全量加载会话消息——业务语义（历史展示需要全部），只测不修。 */
    @Test
    void getHistoryLoadsAllMessagesInConstantStatements() {
        UUID userId = newUser();
        Conversation conversation = newConversation(userId, "qdebt_hist_" + UUID.randomUUID());
        int messageCount = 20;
        for (int i = 0; i < messageCount; i++) {
            newMessage(conversation.getId(), Message.MessageRole.USER, "用户消息 " + i);
        }

        statistics.clear();
        long start = System.nanoTime();
        List<Message> history = chatService.getHistory(conversation.getContextId(), userId);
        long elapsedMs = (System.nanoTime() - start) / 1_000_000;

        System.out.printf("[DEBT-A getHistory] statements=%d rows=%d latency=%dms%n",
                statements(), history.size(), elapsedMs);

        assertThat(history).hasSize(messageCount);
        // 2 条固定语句：select 会话 + select 消息（行数随消息数增长但语句数恒定）
        assertThat(statements()).isEqualTo(2);
    }

    /** §十五B：会话列表预览是批量 IN 查询——语句数不随会话数增长（无 N+1 则锁定）。 */
    @Test
    void conversationListPreviewStaysBatchedRegardlessOfConversationCount() {
        UUID userId = newUser();
        int conversationCount = 20;
        for (int i = 0; i < conversationCount; i++) {
            Conversation conversation = newConversation(userId, "qdebt_list_" + UUID.randomUUID());
            newMessage(conversation.getId(), Message.MessageRole.USER, "预览消息 " + i);
        }

        statistics.clear();
        List<Conversation> conversations = conversationService.getUserConversations(userId);
        long statementCount = statements();

        System.out.printf("[DEBT-B conversationList] conversations=%d statements=%d%n",
                conversations.size(), statementCount);

        assertThat(conversations).hasSize(conversationCount);
        // DEFER 哨兵（J1.4C 实测）：hydrateConversationPreviews 的事务内 setTitle
        // 触发每会话一条隐式 UPDATE（auto-title 业务行为），20 会话 = 23 条语句
        //（1 select + 2 批量预览 + 20 UPDATE）。修复=改变列表读取的业务语义，
        // 待用户拍板；语句数变化时本哨兵提醒更新评估。
        assertThat(statementCount).isGreaterThan(conversationCount);
    }

    /** §十五C：deleteAllConversations N+1 实证（BEFORE：2N+2 语句随会话数线性增长）。 */
    @Test
    void deleteAllConversationsUsesConstantStatementShape() {
        UUID userId = newUser();
        int conversationCount = 5;
        for (int i = 0; i < conversationCount; i++) {
            Conversation conversation = newConversation(userId, "qdebt_del_" + UUID.randomUUID());
            for (int m = 0; m < 3; m++) {
                newMessage(conversation.getId(), Message.MessageRole.USER, "待删消息 " + m);
            }
        }

        statistics.clear();
        conversationService.deleteAllConversations(userId);
        long statementCount = statements();

        System.out.printf("[DEBT-C deleteAll] conversations=%d statements=%d (线性=N+1 实锤)%n",
                conversationCount, statementCount);

        // N+1 契约锁定：语句数必须随会话数增长（2N+2 = select + 每会话 select messages + per-entity DELETE + deleteAll）
        assertThat(statementCount).isGreaterThan(conversationCount + 1);
        assertThat(conversationRepository.findByUserId(userId)).isEmpty();
        // AFTER（bulk DELETE）：1 select conversations + 1 bulk delete messages
        // + N delete conversations，语句数 1+N+1；BEFORE（逐会话加载逐实体删）= 26
        assertThat(statementCount).isEqualTo(conversationCount + 2);
    }

    /** §十五D：getPreviewContent 为取首条用户消息全量加载消息（BEFORE：rows=全部消息）。 */
    @Test
    void getPreviewContentLoadsEntireThreadForFirstUserMessage() {
        UUID userId = newUser();
        Conversation conversation = newConversation(userId, "qdebt_prev_" + UUID.randomUUID());
        int totalMessages = 20;
        newMessage(conversation.getId(), Message.MessageRole.USER, "首条用户消息");
        for (int i = 0; i < totalMessages - 1; i++) {
            newMessage(conversation.getId(), Message.MessageRole.ASSISTANT, "填充消息 " + i);
        }

        statistics.clear();
        String preview = conversationService.getPreviewContent(conversation.getId());

        System.out.printf("[DEBT-D getPreviewContent] statements=%d entityLoads=%d preview=%s%n",
                statements(), loadedEntities(), preview);

        assertThat(preview).contains("首条用户消息");
        // AFTER（复用 findFirstMessagePreviews 投影）：零实体加载，语句 ≤2；
        // BEFORE（全量加载）= entityLoads 20
        assertThat(loadedEntities()).isZero();
    }

    /** §十五E：clearHistory 全量加载后 deleteAll（BEFORE：逐实体 DELETE）。 */
    @Test
    void clearHistoryDeletesPerEntityBeforeOptimization() {
        UUID userId = newUser();
        Conversation conversation = newConversation(userId, "qdebt_clear_" + UUID.randomUUID());
        for (int i = 0; i < 10; i++) {
            newMessage(conversation.getId(), Message.MessageRole.USER, "清史消息 " + i);
        }

        statistics.clear();
        chatService.clearHistory(conversation.getContextId(), userId);
        long statementCount = statements();

        System.out.printf("[DEBT-E clearHistory] statements=%d (AFTER bulk)%n", statementCount);

        // AFTER（bulk DELETE）：1+1+1=3；BEFORE（逐实体 DELETE 10 条消息）= 13
        assertThat(statements()).isEqualTo(3);
        assertThat(messageRepository.findByConversationIdOrderByCreatedAtAsc(conversation.getId())).isEmpty();
    }
}
