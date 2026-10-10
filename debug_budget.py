from app.agent.parser import MockInquiryParser
from app.agent.tool_registry import ToolRegistry
from app.data.repository import default_repository

p = MockInquiryParser().parse("Need a 20-ton excavator for 2 days starting 2026-11-12 in Austin, TX. Budget is ₹5,000 per day. Self-pickup with a licensed operator.")
print(p.model_dump())
r = ToolRegistry(default_repository).execute_tool("calculate_price", p)
print('company_name=', r.data['company_name'])
print('comparison=', r.data['provider_comparison'])
