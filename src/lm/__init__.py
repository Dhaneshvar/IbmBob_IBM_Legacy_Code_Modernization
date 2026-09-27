"""Legacy Modernizer: COBOL/JCL to normalised IR to verified migration.

The pipeline is deliberately layered so that the deterministic stages carry all
of the correctness weight and the LLM stages carry only the *search*:

    1. lex/parse   deterministic, no LLM
    2. IR          deterministic, no LLM
    3. store       deterministic, SQLite (+ optional Neo4j projection)
    4. agents      LLM, planner -> executor -> critic, over IR only
    5. target      deterministic code emission from the executor's decisions
    6. oracle      executes IR and generated code on the same vectors
    7. obs         spans, metrics, AI-Ops report
"""

__version__ = "0.1.0"
