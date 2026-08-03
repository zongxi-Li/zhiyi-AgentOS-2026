"""写作 Pack 的技能实现，提供灵感扩展、大纲、人物关系和正文写作能力。"""


from agent.packs.writer.skills.character_relation_skill import CharacterRelationSkill
from agent.packs.writer.skills.content_write_skill import ContentWriteSkill
from agent.packs.writer.skills.inspiration_expand_skill import InspirationExpandSkill
from agent.packs.writer.skills.outline_generate_skill import OutlineGenerateSkill

__all__ = [
    "InspirationExpandSkill",
    "OutlineGenerateSkill",
    "ContentWriteSkill",
    "CharacterRelationSkill",
]
