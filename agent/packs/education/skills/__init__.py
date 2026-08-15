"""教育 Pack 的技能实现，提供备课、诊断、作业、路径规划和家校沟通能力。"""


from packs.education.skills.classroom_interaction_design_skill import ClassroomInteractionDesignSkill
from packs.education.skills.error_analysis_question_push_skill import ErrorAnalysisQuestionPushSkill
from packs.education.skills.homework_grading_skill import HomeworkGradingSkill
from packs.education.skills.learning_path_planning_skill import LearningPathPlanningSkill
from packs.education.skills.lesson_plan_generation_skill import LessonPlanGenerationSkill
from packs.education.skills.parent_communication_suggestion_skill import ParentCommunicationSuggestionSkill
from packs.education.skills.progress_report_generation_skill import ProgressReportGenerationSkill
from packs.education.skills.student_diagnosis_skill import StudentDiagnosisSkill
from packs.education.skills.tutoring_qa_skill import TutoringQASkill

__all__ = [
    "StudentDiagnosisSkill",
    "LessonPlanGenerationSkill",
    "HomeworkGradingSkill",
    "ErrorAnalysisQuestionPushSkill",
    "TutoringQASkill",
    "LearningPathPlanningSkill",
    "ProgressReportGenerationSkill",
    "ClassroomInteractionDesignSkill",
    "ParentCommunicationSuggestionSkill",
]
