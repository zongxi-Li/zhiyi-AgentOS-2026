package com.kinlin.ai.projection.mission.dto;

/** Run identity and lifecycle facts as observed in Mission history, not live executor state. */
public record MissionRunSummaryQuery(String runId, String missionId, String status, int graphVersion,
                                     String startedAt, String finishedAt, String createdAt, String updatedAt) { }
