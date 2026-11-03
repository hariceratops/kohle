from sqlalchemy.orm import Session

from kohle.domain.models import Rule
from kohle.use_cases.conditions import toml_string
from kohle.use_cases.rules import ApplyRuleFile, PlanRuleFile, ShowRules


def add_rule(session: Session, pattern: str, account: str) -> Rule:
    """Append a rule with a single `any_field` condition, the way a person
    would: by adding it to the rule file and applying that."""
    body = ShowRules(session).execute().unwrap()
    body += f"\n[[rule]]\naccount = {toml_string(account)}\n[rule.when]\nany_field = {toml_string(pattern)}\n"
    base = PlanRuleFile(session).execute(body).unwrap().base
    ApplyRuleFile(session).execute(body, base).unwrap()
    return session.query(Rule).order_by(Rule.id.desc()).first()
