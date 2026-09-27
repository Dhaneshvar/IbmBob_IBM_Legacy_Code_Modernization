Sample 4: Find high-impact migration hotspots

MATCH (p:Program)<-[:HAS_FUNCTION]-(f:Function)
OPTIONAL MATCH (f)-[:CALLS*1..3]->(dep:Function)
RETURN p.name AS program,
       f.name AS function,
       count(DISTINCT dep) AS downstream_functions
ORDER BY downstream_functions DESC
LIMIT 20;

Sample 3: Find all datasets used by a program/job


MATCH (p:Program {name: 'PAYROLL'})<-[:RUNS]-(j:Job)-[:USES_DATASET]->(d:Dataset)
RETURN j.name AS job, d.dsn AS dataset
ORDER BY job, dataset;


Sample 2: Find all functions calling a given function

MATCH (caller:Function)-[:CALLS]->(callee:Function)
WHERE callee.name CONTAINS 'VALIDATE' OR callee.name CONTAINS 'PROCESS' 
RETURN caller.name AS caller, callee.name AS callee
ORDER BY caller;

Sample 1: Show a program’s full dependency subgraph

MATCH (p:Program {name: 'PAYROLL'})
OPTIONAL MATCH (p)-[:HAS_FUNCTION]->(f:Function)
OPTIONAL MATCH (f)-[:CALLS]->(c:Function)
OPTIONAL MATCH (p)-[:DECLARES]->(v:Variable)
OPTIONAL MATCH (f)-[:READS]->(rv:Variable)
OPTIONAL MATCH (f)-[:WRITES]->(wv:Variable)
RETURN p, f, c, v, rv, wv
LIMIT 200;