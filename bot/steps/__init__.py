from bot.steps.domain import DomainStep
from bot.steps.general_prompt import GeneralPromptStep
from bot.steps.table import TableStep
from bot.steps.sub_domain import SubDomainStep
from bot.steps.sub_domain_prompt import SubDomainPromptStep
from bot.steps.few_shot import FewShotStep

ALL_STEPS = [
    DomainStep,
    GeneralPromptStep,
    TableStep,
    SubDomainStep,
    SubDomainPromptStep,
    FewShotStep,
]
