# Rentaliq — AI Equipment Rental Decision Agent

**Rentaliq** is an intelligent, policy-governed decision agent built for heavy equipment rental providers. It interprets unstructured contractor rental inquiries, executes verification tools dynamically, evaluates qualification criteria against hard safety and operational constraints, and produces one of three auditable decisions:

- `AUTO_QUOTE`: All required checks pass, inventory availability is verified, site criteria are satisfied, and pricing is calculated.
- `REQUEST_INFO`: Essential details (such as machine capacity, start date, duration, or delivery location) are missing or ambiguous; targeted follow-up questions are drafted.
- `MANUAL_REVIEW`: Hard policy violations, restrictive site clearances, active schedule conflicts, uninspected units, or verification tool failures require human intervention and authorization.

---

## 1. Architecture & Agent Workflow

The agent orchestrates inquiry evaluations using a structured, 8-step lifecycle:

```
Contractor Inquiry Message
            │
            ▼
   [ 1. Understand ]   ──> Parse equipment, capacity, dates, duration, location, budget, site access
            │
            ▼
   [ 2. Assess ]       ──> Check missing essential fields vs known parameters and risk flags
            │
            ▼
   [ 3. Plan ]         ──> Select required verification strategy (clarification, availability, criteria, pricing)
            │
            ▼
   [ 4. Execute ]      ──> Invoke tools via ToolRegistry (availability, criteria validation, rate matrix)
            │
            ▼
   [ 5. Counter-Offer] ──> Check for verified alternatives (schedule conflicts, duration adjustments, budget cap)
            │
            ▼
   [ 6. Decide ]       ──> Deterministic Policy Engine evaluates qualification scorecard & hard constraints
            │
            ▼
   [ 7. Explain ]      ──> Compute transparent confidence score & compile chronological audit trace
            │
            ▼
   [ 8. Persist ]      ──> Idempotently update SQLite database & return structured DecisionResponse
```

### Key Principles & Safety Guarantees

1. **Deterministic Business Rules**: Hard safety, eligibility, availability, and pricing thresholds are strictly enforced by the policy engine. Model outputs or high confidence scores **never** override a failed critical check.
2. **Zero False Bookings**: Generating a quote or counter-offer **never** alters authoritative inventory or creates a booking.
3. **No External Communications**: No external email, SMS, or WhatsApp channels are connected. All quote drafts and clarification questions are rendered directly in the application interface.
4. **Full Offline Simulation**: The application runs completely offline without any paid external credentials or third-party APIs. When credentials are provided, an optional LLM adapter can be activated.

---

## 2. Repository Structure

```text
rentalagent/
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI application entrypoint & health check
│   ├── config.py                   # Environment settings & configuration parameters
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py               # API endpoints (/evaluate, /demo-inquiries, /inquiries)
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── orchestrator.py         # Multi-step agent loop & dynamic tool coordinator
│   │   ├── parser.py               # MockInquiryParser and optional LLM adapter
│   │   ├── decision_engine.py      # Policy engine & 7-point qualification scorecard
│   │   ├── tool_registry.py        # Central tool registration, execution, and timing logger
│   │   ├── counter_offer.py        # Verified policy-compliant alternative generator
│   │   ├── reasoning.py            # Chronological ReasoningTraceEvent collector
│   │   └── confidence.py           # Transparent 4-factor confidence assessor (0.0 - 1.0)
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── inquiry.py              # InquiryRequest and ParsedInquiry models
│   │   └── decision.py             # DecisionResponse, QualificationCheck, EstimatedQuote, CounterOffer
│   ├── tools/
│   │   ├── __init__.py
│   │   └── interfaces.py           # ToolResult & abstract contracts (Availability, Pricing, Criteria)
│   └── data/
│       ├── __init__.py
│       └── repository.py           # Abstract Repository & thread-safe SQLite persistence layer
├── data/
│   ├── equipment.json              # Synthetic fleet inventory (rates, specs, inspection flags)
│   ├── providers.json              # Provider terms, tax rates, delivery fees, escalation rules
│   ├── contractors.json            # Synthetic contractor credit tiers & operator licenses
│   ├── bookings.json               # Active confirmed reservations causing realistic conflicts
│   ├── policies.json               # Hard rental durations, site access widths, safety rules
│   └── sample_inquiries.json       # 6 required demo scenarios (complete, missing, conflict, risk, budget, tool error)
├── tests/
│   ├── test_parser.py              # Parser heuristics, missing fields, and date validators
│   ├── test_decision_engine.py     # Deterministic decisions & critical precedence enforcement
│   ├── test_orchestrator.py        # End-to-end 6 demo scenarios & context-dependent sequences
│   ├── test_repository.py          # Master data loading, idempotent upserts, and booking safety
│   └── test_api.py                 # FastAPI endpoints and serialization tests
├── .env.example                    # Environment variable template
├── .gitignore
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## 3. Installation & Getting Started

### Prerequisites

- Python 3.11+ (Python 3.14+ fully verified)
- `pip`

### Step 1: Clone & Install Dependencies

```bash
git clone <repo_url>
cd rentalagent
pip install -r requirements.txt
```

### Step 2: Configure Environment (Optional)

Copy `.env.example` to `.env` if you want to customize settings:

```bash
cp .env.example .env
```

By default, `RENTALIQ_EXECUTION_MODE=SIMULATED` is active and requires **no external API keys**.

### Step 3: Run the Test Suite

```bash
python -m pytest -v
```

All 29 tests will execute, validating the parser, decision engine, tool contracts, scenario sequences, and API contracts.

### Step 4: Start the FastAPI Server

```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# Or alternatively:
python app/main.py
```

Once running:
- **Interactive OpenAPI Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Check**: [http://localhost:8000/health](http://localhost:8000/health)

---

## 4. API Documentation & Integration Guide

### `POST /api/v1/agent/evaluate`

Evaluates an inquiry and produces a qualification scorecard, reasoning trace, and handling decision.

#### Request Example (Complete Inquiry)
```json
{
  "inquiry_id": "inq_demo_001",
  "contractor_id": "CON-101",
  "provider_id": "PROV-001",
  "contractor_message": "Need a 20-ton excavator for 4 days starting 2026-11-12 at 1200 East 7th St, Austin TX. Standard open site access with certified operator on our crew. Our budget is $8,000.",
  "project_location": "1200 East 7th St, Austin, TX",
  "metadata": {
    "channel": "web_portal"
  }
}
```

#### Response Example (`AUTO_QUOTE`)
```json
{
  "inquiry_id": "inq_demo_001",
  "decision": "AUTO_QUOTE",
  "decision_reason": "All qualification criteria passed. Verified available Caterpillar 320 GC for 4 days. Total estimated quote: $5,033.62.",
  "parsed_inquiry": {
    "equipment_type": "Excavator",
    "equipment_capacity": "20-ton",
    "start_date": "2026-11-12",
    "end_date": "2026-11-16",
    "duration_days": 4,
    "location": "1200 East 7th St, Austin, TX",
    "budget": 8000.0,
    "operator_required": false,
    "missing_fields": [],
    "uncertain_fields": [],
    "assumptions": []
  },
  "qualification_score": 100.0,
  "qualification_checks": [
    {
      "name": "EQUIPMENT_IDENTIFICATION",
      "status": "PASS",
      "explanation": "Equipment identified: 20-ton Excavator.",
      "criticality": "CRITICAL",
      "evidence_source": "inquiry_parser",
      "weight": 1.5
    },
    {
      "name": "DATES_AND_DURATION",
      "status": "PASS",
      "explanation": "Valid rental period: 2026-11-12 for 4 day(s).",
      "criticality": "CRITICAL",
      "evidence_source": "inquiry_parser",
      "weight": 1.5
    },
    {
      "name": "AVAILABILITY_VERIFICATION",
      "status": "PASS",
      "explanation": "Equipment EQ-CAT-320 (Caterpillar 320 GC) is verified AVAILABLE for dates 2026-11-12 to 2026-11-16.",
      "criticality": "CRITICAL",
      "evidence_source": "inventory_database",
      "weight": 2.0
    },
    {
      "name": "SITE_AND_SAFETY_SUITABILITY",
      "status": "PASS",
      "explanation": "All jobsite access, minimum duration, and safety suitability criteria passed.",
      "criticality": "CRITICAL",
      "evidence_source": "policy_criteria_engine",
      "weight": 1.5
    },
    {
      "name": "OPERATOR_AND_LICENSING",
      "status": "PASS",
      "explanation": "Contractor confirmed self-operation with qualified on-site operator.",
      "criticality": "MEDIUM",
      "evidence_source": "contractor_input",
      "weight": 1.0
    },
    {
      "name": "PRICING_AND_BUDGET",
      "status": "PASS",
      "explanation": "Quote successfully calculated: $5,033.62.",
      "criticality": "HIGH",
      "evidence_source": "rate_matrix",
      "weight": 1.5
    },
    {
      "name": "POLICY_COMPLIANCE",
      "status": "PASS",
      "explanation": "No policy violations detected.",
      "criticality": "HIGH",
      "evidence_source": "decision_policy",
      "weight": 1.0
    }
  ],
  "missing_information": [],
  "estimated_quote": {
    "equipment_id": "EQ-CAT-320",
    "equipment_name": "Caterpillar 320 GC",
    "duration_days": 4,
    "daily_rate": 1100.0,
    "base_amount": 4400.0,
    "operator_fee": 0.0,
    "transport_fee": 250.0,
    "taxes_and_fees": 383.62,
    "total_estimated_amount": 5033.62,
    "line_items": [
      {
        "description": "Caterpillar 320 GC Daily Rental (4 days @ $1100.0/day)",
        "unit_price": 1100.0,
        "quantity": 4.0,
        "total_price": 4400.0
      },
      {
        "description": "Standard Flat-bed Delivery & Retrieval",
        "unit_price": 250.0,
        "quantity": 1.0,
        "total_price": 250.0
      },
      {
        "description": "State & Local Rental Surcharge/Tax (8.25%)",
        "unit_price": 383.62,
        "quantity": 1.0,
        "total_price": 383.62
      }
    ],
    "disclaimer": "Estimated quote only. Subject to provider review and formal rental agreement. Does not constitute an inventory hold or confirmed reservation."
  },
  "counter_offer": null,
  "follow_up_message": "Hello Marcus! We have verified that the Caterpillar 320 GC is available for your project starting 2026-11-12 for 4 days. Your estimated quote total is $5,033.62...",
  "confidence_score": 0.95,
  "requires_human_approval": false,
  "execution_mode": "SIMULATED"
}
```

---

## 5. Team Integration Contracts

### Role A — Agent Lead (This Module)
- **Files Owned**: `app/agent/`, `app/schemas/`, `app/config.py`, `app/main.py`.
- **Responsibilities**: Inquiry parsing, orchestrator loop, decision engine, qualification scorecard, counter-offers, reasoning traces, confidence scoring, shared data contracts.

### Role B — Tools Engineer
- **Files to Extend**: `app/tools/interfaces.py`, `app/agent/tool_registry.py`.
- **Integration Contract**:
  - Implement concrete versions of `AvailabilityTool`, `PricingTool`, and `CriteriaValidationTool`.
  - Register new tools with `orchestrator.tool_registry.register_tool(name, callable)`.
  - Tools must accept `ParsedInquiry` (and optional identifiers) and return a `ToolResult`.
  - When inventory conflict is found, populate `ToolResult.suggested_alternatives` with verified available machines.
  - Set `ToolResult.is_simulated = False` when connecting real APIs.

### Role C — Data and Content Lead
- **Files to Edit**: `data/equipment.json`, `data/providers.json`, `data/contractors.json`, `data/bookings.json`, `data/policies.json`, `data/sample_inquiries.json`.
- **Integration Contract**:
  - Add new fleet units, attachments, risk tiers, and inspection flags in `equipment.json`.
  - Add realistic contractor records and risk tiers in `contractors.json`.
  - Update policy thresholds (e.g. max rental days, operator weight threshold) in `policies.json`.
  - Edit or expand demonstration scenarios in `sample_inquiries.json`.
  - The SQLite repository will automatically reload all JSON files upon restart.

### Role D — UI and Demo Lead
- **API Endpoints to Consume**:
  - `GET /api/v1/agent/demo-inquiries`: Load preconfigured demo scenarios into a dropdown or selector.
  - `POST /api/v1/agent/evaluate`: Submit inquiries for evaluation and display results.
  - `GET /api/v1/agent/inquiries`: Display evaluation history table.
  - `GET /api/v1/agent/inquiries/{inquiry_id}`: Retrieve full evaluation audit view.
- **UI Presentation Requirements**:
  - Display the final decision (`AUTO_QUOTE`, `REQUEST_INFO`, `MANUAL_REVIEW`) with distinct status badges.
  - Render the **Qualification Scorecard** (showing PASS, FAIL, MISSING checks and weighted score).
  - Render the **Tool Execution History** (tools called, latency ms, data source).
  - Render the **Chronological Reasoning Trace** (event timeline).
  - Render any generated message draft (`follow_up_message`) directly on screen as a preview (never send externally).
  - Render itemized quotes and counter-offers when present.

---

## 6. Demonstration Scenarios

The system includes six preconfigured demo scenarios demonstrating context-dependent strategy selection:

| Scenario | Name | Input Key Signals | Tool Path Selected | Expected Decision |
|---|---|---|---|---|
| **Scenario 1** | Complete Standard Request | 20-ton Excavator, dates, location, budget sufficient | `check_availability` -> `validate_criteria` -> `calculate_price` | `AUTO_QUOTE` |
| **Scenario 2** | Missing Details | Missing dates & machine capacity | *Skips all tools* -> plans clarification | `REQUEST_INFO` |
| **Scenario 3** | Unavailable Equipment | Booking collision on requested dates | `check_availability` (fails) -> finds alternatives | `MANUAL_REVIEW` + Verified Counter-Offer |
| **Scenario 4** | Site Risk | 2.2m alley clearance & power lines | `check_availability` -> `validate_criteria` (fails safety) -> skips pricing | `MANUAL_REVIEW` |
| **Scenario 5** | Budget Constraint | $1,800 budget vs $6,200 quote | `check_availability` -> `validate_criteria` -> `calculate_price` (fails budget) -> finds cheaper units | `MANUAL_REVIEW` + Budget Counter-Offer |
| **Scenario 6** | Tool Failure | Simulated telemetry/RPC timeout | `check_availability` (RPC error) -> halts pipeline | `MANUAL_REVIEW` (Fails closed) |

---

## 7. Execution Modes: LLM vs Simulated

| Feature | `SIMULATED` Mode (Default) | `LLM` Mode |
|---|---|---|
| **API Key Required** | None | `RENTALIQ_LLM_API_KEY` |
| **Parsing Engine** | Regex & heuristic NLP token parser | LLM structured JSON output |
| **Tool Execution** | Deterministic synthetic catalog & rules | Autonomous tool selection & parameterization |
| **Audit Label** | `execution_mode: "SIMULATED"` | `execution_mode: "LLM"` |
| **Offline Compatible** | Yes (100% local) | No |
| **Hard Constraint Enforcement** | Strictly enforced by DecisionEngine | Strictly enforced by DecisionEngine (LLM cannot override) |

---

## 8. Known Limitations

1. **Synthetic Data**: Local JSON/SQLite datasets simulate real dispatch telemetry and catalog data.
2. **Read-Only Bookings**: To prevent inventory drift during demonstrations, quotes do not alter inventory availability.
3. **Draft-Only Communications**: Notifications and quote emails are rendered on screen and are not dispatched via external SMTP or SMS gateways.
