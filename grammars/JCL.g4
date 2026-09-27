/**
 * IBM JCL Grammar for ANTLR4
 * Card-image format: // in columns 1-2.
 * Handles JOB, EXEC, DD, PROC, PEND, SET, IF/ENDIF cards.
 */
grammar JCL;

startRule : jclUnit EOF ;

jclUnit   : card* ;

card
    : jobCard
    | execCard
    | ddCard
    | procCard
    | pendCard
    | setCard
    | ifCard
    | includeCard
    | commentCard
    ;

jobCard
    : SLASHSLASH jobName JOB operands? NEWLINE
    ;

execCard
    : SLASHSLASH stepName? EXEC execOperands NEWLINE
    ;

execOperands
    : PGM EQUAL name  (COMMA keywordParam)*
    | PROC? EQUAL? name (COMMA keywordParam)*
    | name             (COMMA keywordParam)*
    ;

ddCard
    : SLASHSLASH ddName DD ddOperands NEWLINE continuationCard*
    ;

ddOperands
    : ASTERISK                   # ddInstream
    | keywordParam (COMMA keywordParam)*  # ddKeyword
    |                             # ddDummy
    ;

continuationCard
    : SLASHSLASH WS keywordParam (COMMA keywordParam)* NEWLINE
    ;

procCard  : SLASHSLASH name? PROC (keywordParam (COMMA keywordParam)*)? NEWLINE ;
pendCard  : SLASHSLASH PEND NEWLINE ;
setCard   : SLASHSLASH SET keywordParam (COMMA keywordParam)* NEWLINE ;
ifCard    : SLASHSLASH IF condition THEN NEWLINE ;
includeCard: SLASHSLASH INCLUDE MEMBER EQUAL name NEWLINE ;
commentCard: SLASHSLASHSTAR ~NEWLINE* NEWLINE ;

keywordParam
    : name EQUAL paramValue
    | name EQUAL LPAREN paramValue (COMMA paramValue)* RPAREN
    ;

paramValue
    : QUOTED_STRING
    | UNQUOTED_VALUE
    | name
    | ASTERISK
    ;

condition : ~NEWLINE+ ;

jobName  : NAME_TOKEN ;
stepName : NAME_TOKEN ;
ddName   : NAME_TOKEN ;
name     : NAME_TOKEN ;

// ── lexer ──────────────────────────────────────────────────────────────────
SLASHSLASH     : '//' ;
SLASHSLASHSTAR : '//*' ;
JOB            : J O B ;
EXEC           : E X E C ;
DD             : D D ;
PGM            : P G M ;
PROC           : P R O C ;
PEND           : P E N D ;
SET            : S E T ;
IF             : I F ;
THEN           : T H E N ;
ENDIF          : E N D I F ;
INCLUDE        : I N C L U D E ;
MEMBER         : M E M B E R ;
EQUAL          : '=' ;
COMMA          : ',' ;
LPAREN         : '(' ;
RPAREN         : ')' ;
ASTERISK       : '*' ;

QUOTED_STRING  : '\'' (~[\'\n] | '\'\'')* '\'' ;
UNQUOTED_VALUE : [A-Za-z0-9@#$._+\-]+ ;
NAME_TOKEN     : [A-Za-z@#$] [A-Za-z0-9@#$\-]* ;

NEWLINE        : [\r\n]+ ;
WS             : [ \t]+ -> skip ;
COMMENT        : '/*' ~[\r\n]* -> skip ;

fragment A:('a'|'A'); fragment B:('b'|'B'); fragment C:('c'|'C'); fragment D:('d'|'D');
fragment E:('e'|'E'); fragment F:('f'|'F'); fragment G:('g'|'G'); fragment H:('h'|'H');
fragment I:('i'|'I'); fragment J:('j'|'J'); fragment K:('k'|'K'); fragment L:('l'|'L');
fragment M:('m'|'M'); fragment N:('n'|'N'); fragment O:('o'|'O'); fragment P:('p'|'P');
fragment Q:('q'|'Q'); fragment R:('r'|'R'); fragment S:('s'|'S'); fragment T:('t'|'T');
fragment U:('u'|'U'); fragment V:('v'|'V'); fragment W:('w'|'W'); fragment X:('x'|'X');
fragment Y:('y'|'Y'); fragment Z:('z'|'Z');
