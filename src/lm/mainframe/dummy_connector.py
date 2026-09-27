"""Dummy z/OS Mainframe connector.

Simulates a connection to an IBM z/OS system. All data is mock — no real
mainframe is required. In production this would be replaced with a real
FTP/SFTP or z/OSMF REST API client.
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# ─────────────────────────────── mock data ────────────────────────────────

_MOCK_COBOL = {
    "PAYROLL": open("tests/fixtures/PAYROLL.cbl").read()
    if __import__("pathlib").Path("tests/fixtures/PAYROLL.cbl").exists()
    else """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYROLL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TOTAL PIC S9(7)V99 COMP-3 VALUE 0.
       PROCEDURE DIVISION.
       MAIN.
           STOP RUN.
""",
    "ORDPRCS": """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDPRCS.
       AUTHOR. LEGACY-TEAM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ORDER-NUM  PIC 9(8)  VALUE 0.
       01  WS-ORDER-AMT  PIC S9(7)V99 COMP-3 VALUE 0.
       01  WS-CUST-ID    PIC X(10) VALUE SPACES.
       01  WS-STATUS     PIC X     VALUE "P".
           88  STATUS-PENDING   VALUE "P".
           88  STATUS-APPROVED  VALUE "A".
           88  STATUS-REJECTED  VALUE "R".
       01  WS-ERR-MSG    PIC X(80).
       PROCEDURE DIVISION.
       MAIN-SECTION SECTION.
       MAIN.
           PERFORM VALIDATE-ORDER.
           PERFORM CALC-DISCOUNT.
           PERFORM WRITE-OUTPUT.
           STOP RUN.
       VALIDATE-ORDER.
           IF WS-ORDER-AMT > 10000
               MOVE "A" TO WS-STATUS
           ELSE
               MOVE "P" TO WS-STATUS
           END-IF.
       CALC-DISCOUNT.
           IF STATUS-APPROVED
               COMPUTE WS-ORDER-AMT = WS-ORDER-AMT * 0.95
           END-IF.
       WRITE-OUTPUT.
           DISPLAY "ORDER: " WS-ORDER-NUM " STATUS: " WS-STATUS.
""",
    "INVNTRY": """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INVNTRY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ITEM-COUNT  PIC 9(5) VALUE 0.
       01  WS-ITEM-TABLE.
           05  WS-ITEM OCCURS 100 TIMES.
               10  WS-ITEM-ID   PIC X(10).
               10  WS-ITEM-QTY  PIC 9(5) COMP.
               10  WS-ITEM-COST PIC S9(7)V99 COMP-3.
       PROCEDURE DIVISION.
       MAIN.
           PERFORM VARYING WS-ITEM-COUNT FROM 1 BY 1
               UNTIL WS-ITEM-COUNT > 100
               MOVE 0 TO WS-ITEM-QTY(WS-ITEM-COUNT)
           END-PERFORM.
           STOP RUN.
""",
}

_MOCK_JCL = {
    "PAYJOB": """\
//PAYJOB   JOB (ACCT001),'PAYROLL PROCESS',CLASS=A,MSGCLASS=X
//STEP01   EXEC PGM=PAYROLL
//SYSOUT   DD SYSOUT=*
//PAYIN    DD DSN=HLQ.PAYROLL.INPUT,DISP=SHR
//PAYOUT   DD DSN=HLQ.PAYROLL.OUTPUT,DISP=(NEW,CATLG)
//
""",
    "ORDJOB": """\
//ORDJOB   JOB (ACCT002),'ORDER PROCESS',CLASS=B
//STEP01   EXEC PGM=ORDPRCS,PARM='DEBUG'
//SYSOUT   DD SYSOUT=*
//ORDIN    DD DSN=HLQ.ORDER.INPUT,DISP=SHR
//ORDOUT   DD DSN=HLQ.ORDER.OUTPUT,DISP=(NEW,CATLG)
//INVOUT   DD DSN=HLQ.INVENTORY.WORK,DISP=(NEW,PASS)
//STEP02   EXEC PGM=INVNTRY
//INVIN    DD DSN=HLQ.INVENTORY.WORK,DISP=(OLD,DELETE)
//
""",
}

_MOCK_SCREENS = {
    "PAYINQ": {
        "type": "BMS",
        "description": "Payroll Inquiry Screen",
        "fields": ["EMPID", "EMPNAME", "DEPTCODE", "PAYRATE"],
    },
    "ORDINQ": {
        "type": "BMS",
        "description": "Order Inquiry Screen",
        "fields": ["ORDERNUM", "CUSTID", "AMOUNT", "STATUS"],
    },
}

_SYSINFO = {
    "hostname": "MVS.MAINFRAME.EXAMPLE.COM",
    "port": 23,
    "sysplex": "PLEX01",
    "zos_version": "z/OS 2.5",
    "lpar": "PROD01",
    "ipl_time": "2024-01-15T06:00:00Z",
    "jobs_active": 42,
    "datasets_catalogued": 15830,
}


# ─────────────────────────────── connector ────────────────────────────────

@dataclass
class MainframeSession:
    host: str
    port: int
    user: str
    connected: bool = False
    connected_at: Optional[str] = None
    sysinfo: dict = field(default_factory=dict)


_sessions: dict[str, MainframeSession] = {}


async def connect(
    host: str,
    port: int,
    user: str,
    password: str,
    session_id: str = "default",
) -> dict:
    """Simulate connecting to z/OS. Always succeeds with mock data."""
    await asyncio.sleep(random.uniform(0.8, 1.5))  # simulate network latency
    session = MainframeSession(
        host=host,
        port=port,
        user=user,
        connected=True,
        connected_at=datetime.utcnow().isoformat() + "Z",
        sysinfo={**_SYSINFO, "hostname": host or _SYSINFO["hostname"]},
    )
    _sessions[session_id] = session
    return {
        "ok": True,
        "session_id": session_id,
        "sysinfo": session.sysinfo,
        "message": f"Connected to {session.sysinfo['hostname']} ({session.sysinfo['zos_version']})",
    }


async def disconnect(session_id: str = "default") -> dict:
    _sessions.pop(session_id, None)
    return {"ok": True, "message": "Disconnected"}


def is_connected(session_id: str = "default") -> bool:
    sess = _sessions.get(session_id)
    return bool(sess and sess.connected)


# ─────────────────────────────── asset browser ────────────────────────────

async def list_assets(
    session_id: str = "default",
    asset_type: Optional[str] = None,
) -> dict:
    """List all mock assets available on the simulated mainframe."""
    await asyncio.sleep(random.uniform(0.2, 0.5))

    cobol_programs = [
        {
            "name": name,
            "type": "COBOL",
            "library": "HLQ.COBOL.SRC",
            "size": len(src),
            "last_modified": "2024-01-10",
        }
        for name, src in _MOCK_COBOL.items()
    ]

    jcl_jobs = [
        {
            "name": name,
            "type": "JCL",
            "library": "HLQ.JCL",
            "size": len(src),
            "last_modified": "2024-01-12",
        }
        for name, src in _MOCK_JCL.items()
    ]

    screens = [
        {
            "name": name,
            "type": "BMS",
            "library": "HLQ.BMS.SRC",
            "description": info["description"],
            "last_modified": "2024-01-08",
        }
        for name, info in _MOCK_SCREENS.items()
    ]

    datasets = [
        {"name": "HLQ.PAYROLL.INPUT",    "type": "DATASET", "recfm": "FB", "lrecl": 80},
        {"name": "HLQ.PAYROLL.OUTPUT",   "type": "DATASET", "recfm": "FB", "lrecl": 80},
        {"name": "HLQ.ORDER.INPUT",      "type": "DATASET", "recfm": "FB", "lrecl": 132},
        {"name": "HLQ.ORDER.OUTPUT",     "type": "DATASET", "recfm": "FB", "lrecl": 132},
        {"name": "HLQ.INVENTORY.WORK",   "type": "DATASET", "recfm": "FB", "lrecl": 80},
    ]

    if asset_type == "COBOL":
        return {"assets": cobol_programs}
    if asset_type == "JCL":
        return {"assets": jcl_jobs}
    if asset_type == "BMS":
        return {"assets": screens}
    if asset_type == "DATASET":
        return {"assets": datasets}

    return {
        "assets": cobol_programs + jcl_jobs + screens + datasets,
        "summary": {
            "cobol": len(cobol_programs),
            "jcl": len(jcl_jobs),
            "screens": len(screens),
            "datasets": len(datasets),
        },
    }


_MOCK_BMS = {
    "PAYINQ": """\
* =================================================================
*  CICS/BMS MAP DEFINITION - PAYROLL INQUIRY (3270 24x80)
* =================================================================
PAYINQM  DFHMSD TYPE=&SYSPARM,MODE=INOUT,LANG=COBOL,STORAGE=AUTO,   *
               CTRL=(FREEKB,FRSET),TERM=3270-2,TIOAPFX=YES
PAYMAP   DFHMDI SIZE=(24,80),LINE=1,COLUMN=1
TITLE    DFHMDF POS=(1,26),ATTRB=(ASKIP,BRT),LENGTH=28,             *
               INITIAL='EMPLOYEE PAYROLL INQUIRY'
EMPIDL   DFHMDF POS=(4,5),ATTRB=(ASKIP,NORM),LENGTH=12,             *
               INITIAL='EMPLOYEE ID:'
EMPID    DFHMDF POS=(4,18),ATTRB=(UNPROT,IC),LENGTH=6
NAME_L   DFHMDF POS=(6,5),ATTRB=(ASKIP,NORM),LENGTH=12,             *
               INITIAL='EMP NAME   :'
NAME     DFHMDF POS=(6,18),ATTRB=(ASKIP,BRT),LENGTH=30
DEPT_L   DFHMDF POS=(8,5),ATTRB=(ASKIP,NORM),LENGTH=12,             *
               INITIAL='DEPARTMENT :'
DEPT     DFHMDF POS=(8,18),ATTRB=(ASKIP,NORM),LENGTH=10
RATE_L   DFHMDF POS=(10,5),ATTRB=(ASKIP,NORM),LENGTH=12,            *
               INITIAL='PAY RATE   :'
RATE     DFHMDF POS=(10,18),ATTRB=(ASKIP,BRT),LENGTH=12
STATUS_L DFHMDF POS=(12,5),ATTRB=(ASKIP,NORM),LENGTH=12,            *
               INITIAL='STATUS     :'
STATUS   DFHMDF POS=(12,18),ATTRB=(ASKIP,BRT),LENGTH=15
MSG      DFHMDF POS=(23,5),ATTRB=(ASKIP,BRT),LENGTH=50,            *
               INITIAL='PRESS ENTER TO QUERY, PF3 TO EXIT'
         DFHMSD TYPE=FINAL
         END
""",
    "ORDINQ": """\
* =================================================================
*  CICS/BMS MAP DEFINITION - ORDER INQUIRY (3270 24x80)
* =================================================================
ORDINQM  DFHMSD TYPE=&SYSPARM,MODE=INOUT,LANG=COBOL,STORAGE=AUTO,   *
               CTRL=(FREEKB,FRSET),TERM=3270-2,TIOAPFX=YES
ORDMAP   DFHMDI SIZE=(24,80),LINE=1,COLUMN=1
HEADER   DFHMDF POS=(1,28),ATTRB=(ASKIP,BRT),LENGTH=24,             *
               INITIAL='CUSTOMER ORDER INQUIRY'
ORDNO_L  DFHMDF POS=(4,5),ATTRB=(ASKIP,NORM),LENGTH=12,             *
               INITIAL='ORDER NUM  :'
ORDNO    DFHMDF POS=(4,18),ATTRB=(UNPROT,IC),LENGTH=8
CUST_L   DFHMDF POS=(6,5),ATTRB=(ASKIP,NORM),LENGTH=12,             *
               INITIAL='CUSTOMER ID:'
CUSTID   DFHMDF POS=(6,18),ATTRB=(ASKIP,BRT),LENGTH=10
AMT_L    DFHMDF POS=(8,5),ATTRB=(ASKIP,NORM),LENGTH=12,             *
               INITIAL='TOTAL AMT  :'
AMT      DFHMDF POS=(8,18),ATTRB=(ASKIP,BRT),LENGTH=14
STAT_L   DFHMDF POS=(10,5),ATTRB=(ASKIP,NORM),LENGTH=12,            *
               INITIAL='DISPATCH   :'
STAT     DFHMDF POS=(10,18),ATTRB=(ASKIP,BRT),LENGTH=12
PROMPT   DFHMDF POS=(23,5),ATTRB=(ASKIP,BRT),LENGTH=45,            *
               INITIAL='ENTER=SEARCH  F3=EXIT  F7=BACK  F8=FORWARD'
         DFHMSD TYPE=FINAL
         END
""",
}

_MOCK_DATASETS = {
    "HLQ.PAYROLL.INPUT": """\
0001001SMITH     JOHN      IT   000850000020240101
0001002JOHNSON   ALICE     FIN  000920000020240101
0001003WILLIAMS  ROBERT    ENG  001050000020240101
0001004BROWN     EMILY     HR   000780000020240101
0001005DAVIS     MICHAEL   MKT  000810000020240101
0001006MILLER    SARAH     IT   000895000020240101
0001007WILSON    JAMES     OPS  000720000020240101
0001008MOORE     JESSICA   ENG  001120000020240101
0001009TAYLOR    DAVID     FIN  000960000020240101
0001010ANDERSON  DANIEL    RND  001250000020240101
""",
    "HLQ.PAYROLL.OUTPUT": """\
HDR20240115PAYROLL BATCH RUN SUMMARY TOTAL_RECS=00000010
REC0001001SMITH     JOHN      GROSS=00085000.00 TAX=00018700.00 NET=00066300.00
REC0001002JOHNSON   ALICE     GROSS=00092000.00 TAX=00020240.00 NET=00071760.00
REC0001003WILLIAMS  ROBERT    GROSS=00105000.00 TAX=00024150.00 NET=00080850.00
REC0001004BROWN     EMILY     GROSS=00078000.00 TAX=00016380.00 NET=00061620.00
REC0001005DAVIS     MICHAEL   GROSS=00081000.00 TAX=00017415.00 NET=00063585.00
TRLTOTAL_GROSS=00441000.00 TOTAL_TAX=00096885.00 TOTAL_NET=00344115.00
""",
    "HLQ.ORDER.INPUT": """\
ORD10001CUST99201202401100001250000USDAPPROVED
ORD10002CUST48112202401100000450000USDPENDING  
ORD10003CUST11049202401100008920000USDAPPROVED 
ORD10004CUST77432202401100000150000USDREJECTED 
ORD10005CUST22391202401100003400000USDAPPROVED 
""",
    "HLQ.ORDER.OUTPUT": """\
ORD10001 PROCESSED DISCOUNT=05% NET=00011875.00 STATUS=CONFIRMED
ORD10002 PENDING   MANUAL REVIEW REQUIRED
ORD10003 PROCESSED DISCOUNT=05% NET=00084740.00 STATUS=CONFIRMED
ORD10004 REJECTED  CREDIT LIMIT EXCEEDED
ORD10005 PROCESSED DISCOUNT=05% NET=00032300.00 STATUS=CONFIRMED
""",
    "HLQ.INVENTORY.WORK": """\
ITM000000100000540000125000RAW-STEEL-ROD
ITM000000200000120000450000ALUMINUM-SHEET
ITM000000300000980000089000COPPER-WIRE-GA12
ITM000000400000330000320000TITANIUM-FASTENER
""",
}


async def get_source(name: str, asset_type: Optional[str] = None) -> Optional[str]:
    """Return the source text for a named asset with case-insensitivity and full dictionary fallback."""
    await asyncio.sleep(random.uniform(0.02, 0.08))
    at = (asset_type or "").upper()
    if at == "COBOL" and name in _MOCK_COBOL:
        return _MOCK_COBOL[name]
    if at == "JCL" and name in _MOCK_JCL:
        return _MOCK_JCL[name]
    if at == "BMS" and name in _MOCK_BMS:
        return _MOCK_BMS[name]
    if at == "DATASET" and name in _MOCK_DATASETS:
        return _MOCK_DATASETS[name]

    # Universal fallback: search all asset collections if type is omitted or mismatched
    for coll in (_MOCK_COBOL, _MOCK_JCL, _MOCK_BMS, _MOCK_DATASETS):
        if name in coll:
            return coll[name]
    return None
