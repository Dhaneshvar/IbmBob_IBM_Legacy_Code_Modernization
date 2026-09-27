/**
 * IBM Enterprise COBOL 85 Grammar for ANTLR4
 * Covers fixed-format and free-format source.
 * Opaque blocks: EXEC SQL ... END-EXEC, EXEC CICS ... END-EXEC.
 */
grammar Cobol85;

// ── entry ──────────────────────────────────────────────────────────────────
startRule : compilationUnit EOF ;

compilationUnit : programUnit+ ;

programUnit
    : identificationDivision
      environmentDivision?
      dataDivision?
      procedureDivision?
    ;

// ── identification division ────────────────────────────────────────────────
identificationDivision
    : (IDENTIFICATION | ID) DIVISION DOT
      PROGRAM_ID DOT programName DOT
      identificationEntry*
    ;

identificationEntry
    : (AUTHOR | INSTALLATION | DATE_WRITTEN | DATE_COMPILED | SECURITY)
      DOT? literal? DOT
    ;

programName : cobolWord | literal ;

// ── environment division ───────────────────────────────────────────────────
environmentDivision
    : ENVIRONMENT DIVISION DOT
      configurationSection?
      inputOutputSection?
    ;

configurationSection
    : CONFIGURATION SECTION DOT
      (sourceComputerParagraph | objectComputerParagraph | specialNamesParagraph)*
    ;

sourceComputerParagraph : SOURCE_COMPUTER DOT (cobolWord DOT)? ;
objectComputerParagraph : OBJECT_COMPUTER DOT (cobolWord DOT)? ;
specialNamesParagraph   : SPECIAL_NAMES DOT specialNameEntry* ;
specialNameEntry        : cobolWord IS cobolWord DOT? ;

inputOutputSection
    : INPUT_OUTPUT SECTION DOT
      fileControlParagraph?
      ioControlParagraph?
    ;

fileControlParagraph : FILE_CONTROL DOT selectStatement* ;
selectStatement
    : SELECT cobolWord ASSIGN TO literal (selectClause)* DOT
    ;
selectClause
    : ORGANIZATION IS? (SEQUENTIAL | INDEXED | RELATIVE)
    | ACCESS MODE? IS? (SEQUENTIAL | RANDOM | DYNAMIC)
    | (RECORD KEY | ALTERNATE RECORD KEY) IS? qualifiedName
    | STATUS IS? qualifiedName
    ;

ioControlParagraph : IO_CONTROL DOT ;

// ── data division ──────────────────────────────────────────────────────────
dataDivision
    : DATA DIVISION DOT
      dataDivisionSection*
    ;

dataDivisionSection
    : fileSection
    | workingStorageSection
    | localStorageSection
    | linkageSection
    ;

fileSection
    : FILE SECTION DOT
      fileDescriptionEntry*
    ;

fileDescriptionEntry
    : (FD | SD) cobolWord fileDescriptionClause* DOT
      dataDescriptionEntry*
    ;

fileDescriptionClause
    : LABEL RECORDS? ARE? (STANDARD | OMITTED | cobolWord+)
    | RECORD CONTAINS? IntegerLiteral (TO IntegerLiteral)? CHARACTERS?
    | BLOCK CONTAINS? IntegerLiteral (TO IntegerLiteral)? (RECORDS | CHARACTERS)?
    | DATA RECORDS? ARE? cobolWord+
    | LINAGE IS? (cobolWord | IntegerLiteral) LINES?
    ;

workingStorageSection : WORKING_STORAGE SECTION DOT dataDescriptionEntry* ;
localStorageSection   : LOCAL_STORAGE  SECTION DOT dataDescriptionEntry* ;
linkageSection        : LINKAGE        SECTION DOT dataDescriptionEntry* ;

dataDescriptionEntry
    : levelNumber (cobolWord | FILLER)?
      dataDescriptionClause*
      DOT
    ;

levelNumber : IntegerLiteral | LEVEL_NUMBER_66 | LEVEL_NUMBER_77 | LEVEL_NUMBER_88 ;

dataDescriptionClause
    : pictureClause
    | usageClause
    | occursClause
    | valueClause
    | redefinesClause
    | signClause
    | justifiedClause
    | blankClause
    | synchronizedClause
    ;

pictureClause  : (PICTURE | PIC) IS? pictureString ;
pictureString  : (~(DOT | COMMA | SEMI))+  ;   // collected as token stream
usageClause    : USAGE IS? usageValue ;
usageValue     : BINARY | COMP | COMP_3 | PACKED_DECIMAL | DISPLAY | INDEX ;
occursClause   : OCCURS IntegerLiteral (TO IntegerLiteral)? TIMES? (DEPENDING ON? qualifiedName)? ;
valueClause    : (VALUE | VALUES) ARE? IS? literal (COMMA? literal)* ;
redefinesClause: REDEFINES cobolWord ;
signClause     : SIGN IS? (LEADING | TRAILING) (SEPARATE CHARACTER?)? ;
justifiedClause: (JUSTIFIED | JUST) RIGHT? ;
blankClause    : BLANK WHEN? ZERO ;
synchronizedClause : (SYNCHRONIZED | SYNC) (LEFT | RIGHT)? ;

// ── procedure division ─────────────────────────────────────────────────────
procedureDivision
    : PROCEDURE DIVISION usingPhrase? DOT
      procedureDivisionBody
    ;

usingPhrase : USING (BY? (REFERENCE | VALUE | CONTENT))? qualifiedName+ ;

procedureDivisionBody
    : section+
    | sentence+
    ;

section
    : cobolWord SECTION DOT?
      paragraph*
    ;

paragraph
    : cobolWord DOT
      sentence*
    ;

sentence : statement+ DOT ;

statement
    : acceptStatement
    | addStatement
    | callStatement
    | closeStatement
    | computeStatement
    | continueStatement
    | deleteStatement
    | displayStatement
    | divideStatement
    | evaluateStatement
    | exitStatement
    | goToStatement
    | ifStatement
    | inspectStatement
    | moveStatement
    | multiplyStatement
    | openStatement
    | performStatement
    | readStatement
    | rewriteStatement
    | searchStatement
    | setStatement
    | sortStatement
    | stopStatement
    | stringStatement
    | subtractStatement
    | unstringStatement
    | writeStatement
    | execStatement
    | gobackStatement
    ;

// ── individual statements ──────────────────────────────────────────────────
acceptStatement  : ACCEPT qualifiedName (FROM identifier)? ;
addStatement     : ADD (addFormat1 | addFormat2) sizeErrorPhrases? (END_ADD)? ;
addFormat1       : identifier+ TO identifier (COMMA? identifier)* ROUNDED? ;
addFormat2       : (identifier | literal)+ (TO identifier+)? GIVING identifier ROUNDED? ;

callStatement
    : CALL (literal | identifier) (USING callArg+)? (RETURNING identifier)?
      onOverflowPhrase? (END_CALL)? ;
callArg          : (BY? (REFERENCE | CONTENT | VALUE))? (identifier | literal | ADDRESS OF identifier) ;
onOverflowPhrase : (ON? OVERFLOW | ON? EXCEPTION) statement+ (NOT ON? EXCEPTION statement+)? ;

closeStatement   : CLOSE (cobolWord (REEL | UNIT)?)+  ;

computeStatement
    : COMPUTE identifier+ (ROUNDED)? EQUAL arithmeticExpression
      sizeErrorPhrases? (END_COMPUTE)? ;

continueStatement : CONTINUE ;

deleteStatement  : DELETE cobolWord RECORD? invalidKeyPhrases? (END_DELETE)? ;

displayStatement : DISPLAY (identifier | literal)+ (UPON cobolWord)? (WITH? NO ADVANCING)? ;

divideStatement  : DIVIDE (identifier | literal) (INTO | BY) (identifier | literal)
                   (GIVING identifier ROUNDED?)? (REMAINDER identifier)?
                   sizeErrorPhrases? (END_DIVIDE)? ;

evaluateStatement
    : EVALUATE evaluateSubject (ALSO evaluateSubject)*
      whenPhrase+
      (END_EVALUATE)? ;

evaluateSubject : identifier | literal | arithmeticExpression | TRUE | FALSE ;

whenPhrase
    : WHEN (OTHER | evaluateCondition (ALSO evaluateCondition)*)
      statement*
    ;

evaluateCondition
    : ANY
    | NOT? (identifier | literal) (THROUGH | THRU) (identifier | literal)
    | NOT? (identifier | literal | arithmeticExpression)
    | condition
    ;

exitStatement    : EXIT (PROGRAM | PARAGRAPH | SECTION | PERFORM | FUNCTION cobolWord)? ;

goToStatement
    : GO TO? cobolWord+ (DEPENDING ON? identifier)?
    ;

gobackStatement  : GOBACK ;

ifStatement
    : IF condition THEN?
      (statement | NEXT SENTENCE)+
      (ELSE (statement | NEXT SENTENCE)+)?
      (END_IF)?
    ;

inspectStatement
    : INSPECT identifier
      (tallyingPhrase | replacingPhrase | convertingPhrase)+
    ;
tallyingPhrase  : TALLYING identifier FOR (ALL | LEADING | TRAILING | CHARACTERS) (BEFORE | AFTER)? ;
replacingPhrase : REPLACING (ALL | LEADING | FIRST | TRAILING | CHARACTERS) (literal | identifier) BY (literal | identifier) ;
convertingPhrase: CONVERTING (literal | identifier) TO (literal | identifier) ;

moveStatement   : MOVE (CORRESPONDING | CORR)? (identifier | literal) TO identifier+ ;

multiplyStatement
    : MULTIPLY (identifier | literal) BY (identifier ROUNDED?)+ sizeErrorPhrases? (END_MULTIPLY)? ;

openStatement   : OPEN (openMode cobolWord+)+ ;
openMode        : INPUT | OUTPUT | IO | EXTEND ;

performStatement
    : PERFORM (performProcedure | performInline) ;
performProcedure
    : cobolWord (THROUGH | THRU)? cobolWord?
      (performTimes | performUntil | performVarying)?
    ;
performInline
    : (WITH? TEST (BEFORE | AFTER))?
      (performTimes | performUntil | performVarying)?
      statement*
      END_PERFORM
    ;
performTimes    : (identifier | IntegerLiteral) TIMES ;
performUntil    : (WITH? TEST (BEFORE | AFTER))? UNTIL condition ;
performVarying
    : VARYING identifier FROM (identifier | literal) BY (identifier | literal)
      UNTIL condition
      (AFTER identifier FROM (identifier | literal) BY (identifier | literal) UNTIL condition)*
    ;

readStatement
    : READ cobolWord (NEXT | PREVIOUS)? RECORD? (INTO identifier)?
      (KEY IS? qualifiedName)?
      atEndPhrases?
      (END_READ)?
    ;

rewriteStatement
    : REWRITE qualifiedName (FROM identifier)?
      invalidKeyPhrases? (END_REWRITE)?
    ;

searchStatement
    : SEARCH ALL? identifier (VARYING identifier)?
      (AT? END statement+)?
      (WHEN condition statement+)+
      (END_SEARCH)?
    ;

setStatement    : SET identifier+ TO (identifier | literal | TRUE | FALSE) ;

sortStatement   : SORT cobolWord (sortKey)* (INPUT PROCEDURE IS? cobolWord)? (OUTPUT PROCEDURE IS? cobolWord)? ;
sortKey         : ON? (ASCENDING | DESCENDING) KEY? qualifiedName+ ;

stopStatement   : STOP (RUN | literal) ;

stringStatement
    : STRING (identifier | literal)+ DELIMITED BY? (identifier | literal | SIZE)
      INTO identifier
      (WITH? POINTER identifier)?
      (END_STRING)?
    ;

subtractStatement
    : SUBTRACT (identifier | literal)+ FROM (identifier ROUNDED?)+ sizeErrorPhrases? (END_SUBTRACT)? ;

unstringStatement
    : UNSTRING identifier
      (DELIMITED BY? (ALL? (identifier | literal) (OR ALL? (identifier | literal))*))?
      INTO (identifier (DELIMITER IN? identifier)? (COUNT IN? identifier)?)+
      (WITH? POINTER identifier)?
      (TALLYING IN? identifier)?
      (END_UNSTRING)?
    ;

writeStatement
    : WRITE qualifiedName (FROM identifier)?
      (BEFORE | AFTER)? ADVANCING? (identifier | IntegerLiteral) (LINE | LINES)?
      invalidKeyPhrases? (END_WRITE)?
    ;

execStatement
    : EXEC (SQL | CICS | DLI) .*? END_EXEC
    ;

// ── shared phrases ─────────────────────────────────────────────────────────
sizeErrorPhrases
    : (ON? SIZE ERROR statement+)?
      (NOT ON? SIZE ERROR statement+)?
    ;

atEndPhrases
    : (AT? END statement+)?
      (NOT AT? END statement+)?
    ;

invalidKeyPhrases
    : (INVALID KEY? statement+)?
      (NOT INVALID KEY? statement+)?
    ;

// ── expressions ────────────────────────────────────────────────────────────
condition
    : NOT? conditionBase (AND | OR NOT? conditionBase)* ;

conditionBase
    : arithmeticExpression relationalOp arithmeticExpression
    | identifier IS? NOT? (NUMERIC | ALPHABETIC | ALPHABETIC_LOWER | ALPHABETIC_UPPER | ZERO | POSITIVE | NEGATIVE)
    | identifier                              // 88-level condition name
    | LPAREN condition RPAREN
    ;

relationalOp
    : EQUAL | NOT EQUAL
    | GREATER (THAN OR EQUAL TO?)?
    | LESS    (THAN OR EQUAL TO?)?
    | LE | GE | NE | LT | GT
    ;

arithmeticExpression
    : term ((PLUS | MINUS) term)* ;

term
    : factor ((MULTIPLY_OP | DIVIDE_OP) factor)* ;

factor
    : PLUS? primary
    | MINUS primary
    | primary POWER_OP primary
    ;

primary
    : identifier
    | literal
    | FUNCTION cobolWord LPAREN (arithmeticExpression (COMMA? arithmeticExpression)*)? RPAREN
    | LPAREN arithmeticExpression RPAREN
    ;

qualifiedName : cobolWord (OF cobolWord)* subscript? ;
subscript     : LPAREN arithmeticExpression (COMMA? arithmeticExpression)* RPAREN ;
identifier    : qualifiedName ;

literal
    : IntegerLiteral
    | DecimalLiteral
    | StringLiteral
    | figurativeConstant
    ;

figurativeConstant
    : ZERO | ZEROS | ZEROES
    | SPACE | SPACES
    | HIGH_VALUE | HIGH_VALUES
    | LOW_VALUE  | LOW_VALUES
    | QUOTE | QUOTES
    | ALL literal
    ;

cobolWord : COBOL_WORD | reservedAsWord ;

reservedAsWord
    : ADDRESS | ADVANCING | AFTER | ALL | ALPHABETIC | ALPHABETIC_LOWER | ALPHABETIC_UPPER
    | ANY | ARE | ASCENDING | ASSIGN | AUTHOR
    | BEFORE | BINARY | BLANK | BLOCK | BY
    | CHARACTERS | CLASS | COMP | COMP_3 | CONTAINS | CONTENT | CONVERTING
    | DATA | DATE_COMPILED | DATE_WRITTEN | DEPENDING | DESCENDING | DISPLAY | DYNAMIC
    | EXTEND | FIRST | FOR | FROM | FUNCTION
    | GIVING | GREATER | HIGH_VALUE | HIGH_VALUES
    | IN | INDEX | INPUT | INSTALLATION | INTO | INVALID | IO
    | JUST | JUSTIFIED | KEY | LABEL | LEADING | LEFT | LESS | LINAGE | LINE | LINES | LOW_VALUE | LOW_VALUES
    | NEGATIVE | NEXT | NO | NOT | NUMERIC | OBJECT_COMPUTER
    | OF | OMITTED | ON | OR | OUTPUT
    | PACKED_DECIMAL | POINTER | POSITIVE | PROCEDURE | QUOTE | QUOTES
    | RANDOM | RECORD | RECORDS | REDEFINES | REEL | REFERENCE | REMAINDER | REPLACING
    | RIGHT | ROUNDED
    | SECURITY | SEPARATE | SIZE | SORT | SOURCE_COMPUTER | SPECIAL_NAMES | STANDARD | STATUS | SYNC | SYNCHRONIZED
    | TALLYING | TEST | THROUGH | THRU | TIMES | TO | TRAILING | TRUE
    | UNIT | UNTIL | UPON | USAGE | USING
    | VALUE | VALUES | VARYING
    | WHEN | WITH | ZERO | ZEROS | ZEROES
    ;

// ── lexer ──────────────────────────────────────────────────────────────────
IDENTIFICATION : I D E N T I F I C A T I O N ;
ID             : I D ;
PROGRAM_ID     : P R O G R A M '-' I D ;
AUTHOR         : A U T H O R ;
INSTALLATION   : I N S T A L L A T I O N ;
DATE_WRITTEN   : D A T E '-' W R I T T E N ;
DATE_COMPILED  : D A T E '-' C O M P I L E D ;
SECURITY       : S E C U R I T Y ;
ENVIRONMENT    : E N V I R O N M E N T ;
CONFIGURATION  : C O N F I G U R A T I O N ;
SOURCE_COMPUTER: S O U R C E '-' C O M P U T E R ;
OBJECT_COMPUTER: O B J E C T '-' C O M P U T E R ;
SPECIAL_NAMES  : S P E C I A L '-' N A M E S ;
INPUT_OUTPUT   : I N P U T '-' O U T P U T ;
FILE_CONTROL   : F I L E '-' C O N T R O L ;
IO_CONTROL     : I '-' O '-' C O N T R O L ;
DATA           : D A T A ;
FILE           : F I L E ;
WORKING_STORAGE: W O R K I N G '-' S T O R A G E ;
LOCAL_STORAGE  : L O C A L '-' S T O R A G E ;
LINKAGE        : L I N K A G E ;
PROCEDURE      : P R O C E D U R E ;
DIVISION       : D I V I S I O N ;
SECTION        : S E C T I O N ;
FD             : F D ;
SD             : S D ;
PICTURE        : P I C T U R E ;
PIC            : P I C ;
USAGE          : U S A G E ;
BINARY         : B I N A R Y ;
COMP           : C O M P ;
COMP_3         : C O M P '-' '3' ;
PACKED_DECIMAL : P A C K E D '-' D E C I M A L ;
DISPLAY        : D I S P L A Y ;
INDEX          : I N D E X ;
OCCURS         : O C C U R S ;
VALUE          : V A L U E ;
VALUES         : V A L U E S ;
REDEFINES      : R E D E F I N E S ;
SIGN           : S I G N ;
LEADING        : L E A D I N G ;
TRAILING       : T R A I L I N G ;
JUSTIFIED      : J U S T I F I E D ;
JUST           : J U S T ;
BLANK          : B L A N K ;
SYNCHRONIZED   : S Y N C H R O N I Z E D ;
SYNC           : S Y N C ;
ACCEPT         : A C C E P T ;
ADD            : A D D ;
CALL           : C A L L ;
CLOSE          : C L O S E ;
COMPUTE        : C O M P U T E ;
CONTINUE       : C O N T I N U E ;
DELETE         : D E L E T E ;
DIVIDE         : D I V I D E ;
EVALUATE       : E V A L U A T E ;
EXIT           : E X I T ;
GO             : G O ;
GOBACK         : G O B A C K ;
IF             : I F ;
INSPECT        : I N S P E C T ;
MOVE           : M O V E ;
MULTIPLY       : M U L T I P L Y ;
OPEN           : O P E N ;
PERFORM        : P E R F O R M ;
READ           : R E A D ;
REWRITE        : R E W R I T E ;
SEARCH         : S E A R C H ;
SET            : S E T ;
SORT           : S O R T ;
STOP           : S T O P ;
STRING         : S T R I N G ;
SUBTRACT       : S U B T R A C T ;
UNSTRING       : U N S T R I N G ;
WRITE          : W R I T E ;
EXEC           : E X E C ;
END_EXEC       : E N D '-' E X E C ;
SQL            : S Q L ;
CICS           : C I C S ;
DLI            : D L I ;
END_ADD        : E N D '-' A D D ;
END_CALL       : E N D '-' C A L L ;
END_COMPUTE    : E N D '-' C O M P U T E ;
END_DELETE     : E N D '-' D E L E T E ;
END_DIVIDE     : E N D '-' D I V I D E ;
END_EVALUATE   : E N D '-' E V A L U A T E ;
END_IF         : E N D '-' I F ;
END_MULTIPLY   : E N D '-' M U L T I P L Y ;
END_PERFORM    : E N D '-' P E R F O R M ;
END_READ       : E N D '-' R E A D ;
END_REWRITE    : E N D '-' R E W R I T E ;
END_SEARCH     : E N D '-' S E A R C H ;
END_STRING     : E N D '-' S T R I N G ;
END_SUBTRACT   : E N D '-' S U B T R A C T ;
END_UNSTRING   : E N D '-' U N S T R I N G ;
END_WRITE      : E N D '-' W R I T E ;

TO             : T O ;
FROM           : F R O M ;
GIVING         : G I V I N G ;
ROUNDED        : R O U N D E D ;
SIZE           : S I Z E ;
ERROR          : E R R O R ;
CORRESPONDING  : C O R R E S P O N D I N G ;
CORR           : C O R R ;
AT             : A T ;
END            : E N D ;
NEXT           : N E X T ;
PREVIOUS       : P R E V I O U S ;
INTO           : I N T O ;
KEY            : K E Y ;
INVALID        : I N V A L I D ;
ALL            : A L L ;
RECORD         : R E C O R D ;
RECORDS        : R E C O R D S ;
BEFORE         : B E F O R E ;
AFTER          : A F T E R ;
ADVANCING      : A D V A N C I N G ;
LINE           : L I N E ;
LINES          : L I N E S ;
UPON           : U P O N ;
NO             : N O ;
WITH           : W I T H ;
USING          : U S I N G ;
RETURNING      : R E T U R N I N G ;
BY             : B Y ;
REFERENCE      : R E F E R E N C E ;
CONTENT        : C O N T E N T ;
OVERFLOW       : O V E R F L O W ;
EXCEPTION      : E X C E P T I O N ;
NOT            : N O T ;
ON             : O N ;
DEPENDING      : D E P E N D I N G ;
VARYING        : V A R Y I N G ;
UNTIL          : U N T I L ;
TIMES          : T I M E S ;
TEST           : T E S T ;
WHEN           : W H E N ;
OTHER          : O T H E R ;
ALSO           : A L S O ;
THROUGH        : T H R O U G H ;
THRU           : T H R U ;
ASCENDING      : A S C E N D I N G ;
DESCENDING     : D E S C E N D I N G ;
TALLYING       : T A L L Y I N G ;
REPLACING      : R E P L A C I N G ;
CONVERTING     : C O N V E R T I N G ;
CHARACTERS     : C H A R A C T E R S ;
DELIMITED      : D E L I M I T E D ;
DELIMITER      : D E L I M I T E R ;
COUNT          : C O U N T ;
POINTER        : P O I N T E R ;
REMAINDER      : R E M A I N D E R ;
REEL           : R E E L ;
UNIT           : U N I T ;
DYNAMIC        : D Y N A M I C ;
RANDOM         : R A N D O M ;
SEQUENTIAL     : S E Q U E N T I A L ;
INDEXED        : I N D E X E D ;
RELATIVE       : R E L A T I V E ;
ORGANIZATION   : O R G A N I Z A T I O N ;
ACCESS         : A C C E S S ;
MODE           : M O D E ;
STATUS         : S T A T U S ;
ALTERNATE      : A L T E R N A T E ;
LABEL          : L A B E L ;
STANDARD       : S T A N D A R D ;
OMITTED        : O M I T T E D ;
BLOCK          : B L O C K ;
CONTAINS       : C O N T A I N S ;
LINAGE         : L I N A G E ;
POSITIVE       : P O S I T I V E ;
NEGATIVE       : N E G A T I V E ;
ZERO           : Z E R O ;
ZEROS          : Z E R O S ;
ZEROES         : Z E R O E S ;
SPACE          : S P A C E ;
SPACES         : S P A C E S ;
HIGH_VALUE     : H I G H '-' V A L U E ;
HIGH_VALUES    : H I G H '-' V A L U E S ;
LOW_VALUE      : L O W '-' V A L U E ;
LOW_VALUES     : L O W '-' V A L U E S ;
QUOTE          : Q U O T E ;
QUOTES         : Q U O T E S ;
TRUE           : T R U E ;
FALSE          : F A L S E ;
ANY            : A N Y ;
NUMERIC        : N U M E R I C ;
ALPHABETIC     : A L P H A B E T I C ;
ALPHABETIC_LOWER: A L P H A B E T I C '-' L O W E R ;
ALPHABETIC_UPPER: A L P H A B E T I C '-' U P P E R ;
FUNCTION       : F U N C T I O N ;
ADDRESS        : A D D R E S S ;
ARE            : A R E ;
IS             : I S ;
IN             : I N ;
OF             : O F ;
RUN            : R U N ;
PROGRAM        : P R O G R A M ;
PARAGRAPH      : P A R A G R A P H ;
PERFORM        : P E R F O R M ;
INPUT          : I N P U T ;
OUTPUT         : O U T P U T ;
IO             : I '-' O ;
EXTEND         : E X T E N D ;
FILLER         : F I L L E R ;
SEPARATE       : S E P A R A T E ;
CHARACTER      : C H A R A C T E R ;
RIGHT          : R I G H T ;
LEFT           : L E F T ;
FOR            : F O R ;
CLASS          : C L A S S ;
ASSIGN         : A S S I G N ;
FIRST          : F I R S T ;
THEN           : T H E N ;
ELSE           : E L S E ;
OBJECT_COMPUTER: O B J E C T '-' C O M P U T E R ;
DATA_COMPILED  : D A T A '-' C O M P I L E D ;

LEVEL_NUMBER_66 : '66' ;
LEVEL_NUMBER_77 : '77' ;
LEVEL_NUMBER_88 : '88' ;

EQUAL    : '=' | E Q U A L ;
LT       : '<' ;
GT       : '>' ;
LE       : '<=' ;
GE       : '>=' ;
NE       : '<>' | '/=' ;
GREATER  : G R E A T E R ;
LESS     : L E S S ;
THAN     : T H A N ;
OR       : O R ;
AND      : A N D ;
PLUS     : '+' ;
MINUS    : '-' ;
MULTIPLY_OP : '*' ;
DIVIDE_OP   : '/' ;
POWER_OP    : '**' ;
LPAREN   : '(' ;
RPAREN   : ')' ;
DOT      : '.' ;
COMMA    : ',' ;
SEMI     : ';' ;
COLON    : ':' ;

IntegerLiteral  : [0-9]+ ;
DecimalLiteral  : [0-9]* '.' [0-9]+ | [0-9]+ '.' [0-9]* ;
StringLiteral   : '"' (~["\r\n] | '""')* '"'
                | '\'' (~['\r\n] | '\'\'')* '\''
                ;

COBOL_WORD      : [A-Za-z_] [A-Za-z0-9_\-]* ;

NEWLINE         : [\r\n]+ -> skip ;
WS              : [ \t]+ -> skip ;
LINE_COMMENT    : '*>' ~[\r\n]* -> skip ;
SEQUENCE_AREA   : { getCharPositionInLine() < 6 }? [0-9 ]+ -> skip ;
INDICATOR_AREA  : { getCharPositionInLine() == 6 }? [*/\- ] -> skip ;

// case-insensitive fragments
fragment A:('a'|'A'); fragment B:('b'|'B'); fragment C:('c'|'C'); fragment D:('d'|'D');
fragment E:('e'|'E'); fragment F:('f'|'F'); fragment G:('g'|'G'); fragment H:('h'|'H');
fragment I:('i'|'I'); fragment J:('j'|'J'); fragment K:('k'|'K'); fragment L:('l'|'L');
fragment M:('m'|'M'); fragment N:('n'|'N'); fragment O:('o'|'O'); fragment P:('p'|'P');
fragment Q:('q'|'Q'); fragment R:('r'|'R'); fragment S:('s'|'S'); fragment T:('t'|'T');
fragment U:('u'|'U'); fragment V:('v'|'V'); fragment W:('w'|'W'); fragment X:('x'|'X');
fragment Y:('y'|'Y'); fragment Z:('z'|'Z');
