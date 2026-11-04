"""Native business skill identities and their explicit creation formats."""
SKILL_BY_FORMAT = {'poster': 'oil-pig-poster', 'article': 'oil-pig-article'}
FORMAT_BY_SKILL = {skill: format for format, skill in SKILL_BY_FORMAT.items()}
LEGACY_SKILL = 'content-production'
PRODUCTION_SKILLS = frozenset((*FORMAT_BY_SKILL, LEGACY_SKILL))
