import time
import hashlib
from uuid import uuid4
from datetime import date
from threading import Lock
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from .config import cors_middleware_options, get_settings
from .db import Base, engine, get_db
from .models import HealthRecord, Renewal, Document
from .repositories import Repository
from .schemas import (
    DocumentUpload,
    HealthCreate,
    InvestmentConfirmRequest,
    InvestmentMFARequest,
    InvestmentProposalRequest,
    LoginRequest,
    RenewalCreate,
    RenewalUpdate,
    RouteRequest,
)
from .seed import seed
from .auth import current_user, create_access_token, verify_password, require_permission, revoke_token
from .services import confirm_proposal, create_proposal, route_request, serialize_health, serialize_proposal, serialize_renewal
from .models import InvestmentApproval, InvestmentProposal
from .approval import ApprovalState, transition, verify_mfa
from .routing.supervisor import SupervisorRoutingService
from .routing.broker import MockBrokerGateway
from .routing.audit import AuditEvent
from .routing.contracts import Intent
from .audit_context import audit_request
from .documents.chunking import chunk_text
from .documents.contracts import DocumentType
from .documents.tfidf import lexical_tfidf_search
from .audit import audit

settings=get_settings()
@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    if settings.seed_demo_data:
        seed()
    yield

app=FastAPI(title="PersonalOS API",version="3.0.0", lifespan=lifespan)
@app.middleware("http")
async def add_audit_request_id(request: Request, call_next):
    request_id = str(uuid4())
    with audit_request(request_id):
        return await call_next(request)
supervisor_service = SupervisorRoutingService()
broker_gateway = MockBrokerGateway()
cors_options = cors_middleware_options(settings.origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_options["allow_origins"],
    allow_credentials=cors_options["allow_credentials"],
    allow_methods=["*"],
    allow_headers=["*"],
)
Base.metadata.create_all(engine)
if settings.seed_demo_data: seed()
def repo(db,user): return Repository(db,user.id if user else None)
def public_user(u): return {"id":u.id,"name":u.name,"email":u.email,"role":u.role,"permissions":u.permissions or []}
def audit_cross_user_lookup(db, user, model, resource_id, resource_type, lookup_field="id"):
    record = db.query(model).filter(getattr(model, lookup_field) == resource_id, model.owner_id != user.id).first()
    if record:
        audit(db, user, "cross-user-access-denied", {
            "resource_type": resource_type,
            "resource_id": resource_id,
        })
@app.get("/api/healthz")
def healthz(): return {"status":"ok","service":settings.app_name}
_login_failures: dict[tuple[str, str], list[float]] = {}
_login_limiter_lock = Lock()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


@app.post("/api/auth/login")
def login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    username = payload.email.strip().lower()
    key = (_client_ip(request), username)
    now = time.monotonic()
    with _login_limiter_lock:
        recent = [timestamp for timestamp in _login_failures.get(key, []) if now - timestamp < 60]
        if len(recent) >= 5:
            _login_failures[key] = recent
            audit(db, None, "login-rate-limited", {"email": username, "ip": _client_ip(request)})
            raise HTTPException(status_code=429, detail="Too many login attempts")

    u = Repository(db).user(username)
    if not u or not verify_password(payload.password, u.password_hash):
        with _login_limiter_lock:
            recent = [timestamp for timestamp in _login_failures.get(key, []) if now - timestamp < 60]
            recent.append(time.monotonic())
            _login_failures[key] = recent
        audit(db, None, "login-failed", {"email": username, "ip": _client_ip(request)})
        raise HTTPException(401, "Invalid credentials")

    with _login_limiter_lock:
        _login_failures.pop(key, None)
    audit(db, u, "login", {"email": u.email, "success": True})
    return {"token": create_access_token(u), "user": public_user(u)}
@app.get("/api/auth/me")
def me(user=Depends(current_user)): return {"user":public_user(user)}
@app.post("/api/auth/logout")
def logout(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    revoke_token(request, db, user)
    audit(db, user, "logout")
    return {"success": True}
@app.get("/api/renewals")
def list_renewals(db=Depends(get_db),user=Depends(require_permission("renewal.read"))):
    audit(db,user,"renewals-read"); return {"renewals":[serialize_renewal(x) for x in repo(db,user).renewals()]}
@app.post("/api/renewals",status_code=201)
def create_renewal(p:RenewalCreate,db=Depends(get_db),user=Depends(require_permission("renewal.create"))):
    x=Renewal(owner_id=user.id,name=p.name,category=p.category,due_date=p.dueDate,reminder_days=p.reminderDays,status="upcoming"); db.add(x); db.commit(); db.refresh(x); audit(db,user,"renewal-created"); return {"item":serialize_renewal(x)}
@app.put("/api/renewals/{item_id}")
def update_renewal(item_id,p:RenewalUpdate,db=Depends(get_db),user=Depends(require_permission("renewal.update"))):
    x=db.get(Renewal,item_id)
    if not x or x.owner_id != user.id: raise HTTPException(404,"Renewal not found")
    for k,v in p.model_dump(exclude_unset=True).items(): setattr(x,{"dueDate":"due_date","reminderDays":"reminder_days"}.get(k,k),v)
    x.owner_id=user.id; db.commit(); return {"renewal":serialize_renewal(x)}
@app.delete("/api/renewals/{item_id}")
def delete_renewal(item_id,db=Depends(get_db),user=Depends(require_permission("renewal.delete"))):
    x=db.get(Renewal,item_id)
    if not x or x.owner_id != user.id:
        audit_cross_user_lookup(db, user, Renewal, item_id, "renewal")
        raise HTTPException(404,"Renewal not found")
    result=serialize_renewal(x); db.delete(x); db.commit(); audit(db,user,"renewal-deleted"); return {"deleted":result}
@app.get("/api/health")
def list_health(db=Depends(get_db),user=Depends(require_permission("health.read"))): return {"records":[serialize_health(x) for x in repo(db,user).health()]}
@app.post("/api/health",status_code=201)
def create_health(p:HealthCreate,db=Depends(get_db),user=Depends(require_permission("health.create"))):
    x=HealthRecord(owner_id=user.id,date=p.date or date.today(),metric=p.metric,value=p.value,unit=p.unit); db.add(x); db.commit(); db.refresh(x); return {"record":serialize_health(x)}
@app.post("/api/health/insights")
def health_insights(db=Depends(get_db),user=Depends(require_permission("health.read"))):
    records=[serialize_health(x) for x in repo(db,user).health()]; sleeps=[x["value"] for x in records if x["metric"]=="sleep"]; audit(db,user,"health-insight-generated")
    return {"sensitive":True,"rawData":records,"statisticalObservation":{"averageSleepHours":f"{sum(sleeps)/len(sleeps):.1f}" if sleeps else "0.0"},"aiInterpretation":{"summary":"The observed pattern is an observational summary only.","caution":"Do not treat these results as a diagnosis."}}
@app.get("/api/stock/summary")
def stock_summary(db=Depends(get_db),user=Depends(require_permission("stock.read"))):
    h=[{"symbol":x.symbol,"shares":x.shares,"price":x.price,"allocation":x.allocation} for x in repo(db,user).holdings()]; return {"portfolio":h,"totalValue":sum(x["shares"]*x["price"] for x in h),"risk":"Moderate"}
@app.post("/api/stock/analyze")
def stock_analyze(p:RouteRequest,db=Depends(get_db),user=Depends(require_permission("stock.analyze"))): return route_request(p.query or "portfolio",repo(db,user))
@app.post("/api/investment/propose")
def investment_propose(p:InvestmentProposalRequest,db=Depends(get_db),user=Depends(require_permission("investment.propose"))):
    x=create_proposal(repo(db,user),p.symbol,p.amount,p.riskLevel); audit(db,user,"investment-proposal"); return {"proposal":serialize_proposal(x)}

@app.post("/api/investment/{proposal_id}/mfa/verify")
def investment_mfa(proposal_id: str, p: InvestmentMFARequest, db=Depends(get_db),
                   user=Depends(require_permission("investment.confirm"))):
    r = repo(db, user); x = r.proposal(proposal_id); approval = r.approval(proposal_id)
    if not x or not approval:
        audit_cross_user_lookup(db, user, InvestmentProposal, proposal_id, "investment-proposal")
        audit_cross_user_lookup(db, user, InvestmentApproval, proposal_id, "investment-approval", "proposal_id")
        raise HTTPException(404, "Investment proposal not found")
    try:
        verify_mfa(approval, user_id=user.id, code=p.code)
    except HTTPException as exc:
        db.commit()
        audit(db, user, "investment-mfa-failed",
              {"proposalId": proposal_id, "reason": exc.detail, "provider": "mock-dev"})
        raise
    db.commit()
    audit(db, user, "investment-mfa-verified", {"proposalId": proposal_id, "provider": "mock-dev"})
    audit(db, user, "approval-state-transition", {
        "proposalId": proposal_id,
        "from": ApprovalState.PENDING_MFA.value,
        "to": ApprovalState.APPROVED.value,
    })
    return {"proposal": serialize_proposal(x, approval)}

@app.post("/api/investment/confirm")
def investment_confirm(p:InvestmentConfirmRequest,db=Depends(get_db),user=Depends(require_permission("investment.confirm"))):
    r=repo(db,user); x=r.proposal(p.proposalId) if p.proposalId else None
    if not x:
        if p.proposalId:
            audit_cross_user_lookup(db, user, InvestmentProposal, p.proposalId, "investment-proposal")
            audit_cross_user_lookup(db, user, InvestmentApproval, p.proposalId, "investment-approval", "proposal_id")
        if not p.symbol or p.amount is None: raise HTTPException(404,"Investment proposal not found")
        x=create_proposal(r,p.symbol,p.amount,"Medium")
    approval = r.approval(x.id)
    if not approval:
        approval = InvestmentApproval(proposal_id=x.id, owner_id=user.id, requested_by=user.id)
        db.add(approval); db.flush()
    if p.approved:
        if ApprovalState(approval.status) is ApprovalState.PENDING_USER:
            transition(approval, ApprovalState.PENDING_MFA, user_id=user.id)
            audit(db, user, "approval-state-transition", {
                "proposalId": x.id,
                "from": ApprovalState.PENDING_USER.value,
                "to": ApprovalState.PENDING_MFA.value,
            })
        if ApprovalState(approval.status) is ApprovalState.PENDING_MFA and not p.mfa_code:
            db.commit()
            audit(db, user, "investment-approval-awaiting-mfa",
                  {"proposalId": x.id, "state": approval.status})
            raise HTTPException(status_code=403, detail={
                "code": "investment_execution_denied",
                "reason": "MFA verification is required",
                "mfa_required": True})
        if ApprovalState(approval.status) is ApprovalState.PENDING_MFA:
            try:
                verify_mfa(approval, user_id=user.id, code=p.mfa_code)
            except HTTPException as exc:
                db.commit()
                audit(db, user, "investment-mfa-failed",
                      {"proposalId": x.id, "reason": exc.detail, "provider": "mock-dev"})
                raise
        # Confirmation is a policy boundary. The gateway is called only after
        # the proposal has been explicitly approved and policy checks passed.
        decision = supervisor_service.policy.evaluate(
            Intent.INVESTMENT_EXECUTION, set(user.permissions or []), approved=True,
            mfa_verified=approval.mfa_verified_at is not None, user=user, ownership_verified=True,
            request_id=f"investment-confirmation:{x.id}")
        if not decision.allowed or approval.mfa_verified_at is None:
            audit(db, user, "investment-execution-denied", {
                "proposalId": x.id, "reason": decision.reason,
                "mfa_verified": approval.mfa_verified_at is not None})
            raise HTTPException(status_code=403, detail={
                "code": "investment_execution_denied",
                "reason": decision.reason,
                "mfa_required": True,
                "request_id": decision.decision.request_id if decision.decision else None,
            })
        broker_gateway.execute({"symbol": x.symbol, "amount": x.amount},
                              policy=decision.decision, approved=True,
                              mfa_verified=approval.mfa_verified_at is not None)
        transition(approval, ApprovalState.EXECUTED, user_id=user.id)
        audit(db, user, "approval-state-transition", {
            "proposalId": x.id,
            "from": ApprovalState.APPROVED.value,
            "to": ApprovalState.EXECUTED.value,
        })
        db.commit()
    else:
        transition(approval, ApprovalState.REJECTED, user_id=user.id)
        audit(db, user, "approval-state-transition", {
            "proposalId": x.id,
            "from": ApprovalState.PENDING_USER.value,
            "to": ApprovalState.REJECTED.value,
        })
        db.commit()
    result = serialize_proposal(confirm_proposal(r,x,p.approved,user.name), approval)
    audit(db, user, "investment-confirmation", AuditEvent.create(
        "investment-confirmation", user.id,
        {"proposalId": x.id, "approved": p.approved}).details)
    if not p.approved: return {"status":"rejected","message":"Execution not approved by user."}
    return {"status":"sandbox_execute","broker":result["broker"],"message":"Mock broker request is ready for execution in sandbox mode after MFA and audit verification."}
@app.post("/api/supervisor/route")
def supervisor(p:RouteRequest,db=Depends(get_db),user=Depends(require_permission("supervisor.route"))):
    try:
        result=supervisor_service.route(p.query,repo(db,user),user)
    except ValueError as exc:
        audit(db, user, "supervisor-validation-failed",
              {"query_length": len(p.query), "query_sha256": hashlib.sha256(p.query.encode()).hexdigest(), "reason": str(exc)})
        raise HTTPException(422, str(exc))
    except PermissionError as exc:
        audit(db, user, "supervisor-policy-denied",
              {"query_length": len(p.query), "query_sha256": hashlib.sha256(p.query.encode()).hexdigest(), "reason": str(exc)})
        raise HTTPException(403, str(exc))
    routed_decision = result.get("routing_decision") or {}
    audit(db,user,"supervisor-routed",{
        "query_length": len(p.query),
        "query_sha256": hashlib.sha256(p.query.encode()).hexdigest(),
        "routing_path": result.get("routing_path"),
        "fallback_reason": result.get("fallback_reason"),
        "agent": result["agent"],
        "capability": routed_decision.get("capability"),
        "policy_verdict": "allowed" if (result.get("policy") or {}).get("allowed") else "denied",
        "workflow": result.get("workflow"),
    })
    tool_name = "renewal.read" if result.get("workflow") == "renewal" else "health.read" if result.get("workflow") == "health" else None
    if tool_name:
        audit(db, user, "agent-tool-call", {"tool": tool_name, "ok": True})
    return result

@app.post("/api/documents")
def ingest_document(payload: DocumentUpload, db=Depends(get_db),
                    user=Depends(require_permission("document.create"))):
    text_bytes = payload.text.encode("utf-8")
    if len(text_bytes) > 200 * 1024:
        raise HTTPException(413, "Document exceeds 200 KB")
    document = Document(
        owner_id=user.id,
        filename=payload.filename,
        document_type="general",
        content_type="text/plain",
        status="ingested",
        source="upload",
        metadata_json={},
    )
    db.add(document)
    db.flush()
    chunks = chunk_text(
        payload.text,
        document_id=document.id,
        owner_id=user.id,
        filename=payload.filename,
        document_type=DocumentType.GENERAL,
        chunk_size=800,
        overlap=100,
    )
    document.metadata_json = {
        "chunks": [{"chunk_id": chunk.chunk_id, "text": chunk.text} for chunk in chunks]
    }
    db.commit()
    db.refresh(document)
    audit(db, user, "document-ingested", {
        "text_length": len(payload.text),
        "sha256": hashlib.sha256(text_bytes).hexdigest(),
        "chunk_count": len(chunks),
    })
    return {"document": {
        "id": document.id,
        "filename": document.filename,
        "chunk_count": len(chunks),
    }}

@app.get("/api/documents/search")
def search_documents(q: str, limit: int=5, db=Depends(get_db),
                     user=Depends(require_permission("document.read"))):
    limit = max(1, min(limit, 20))
    repository = repo(db, user)
    chunks: list[dict] = []
    for document in repository.documents(limit=1000):
        for chunk in (document.metadata_json or {}).get("chunks", []):
            chunks.append({
                "document_id": document.id,
                "filename": document.filename,
                "chunk_id": chunk["chunk_id"],
                "text": chunk["text"],
            })
    results = lexical_tfidf_search(q, chunks, limit)
    audit(db, user, "document-searched", {
        "query_length": len(q),
        "query_sha256": hashlib.sha256(q.encode("utf-8")).hexdigest(),
        "result_count": len(results),
    })
    return {"results": results}

@app.get("/api/documents/{document_id}")
def get_document(document_id: str, db=Depends(get_db),
                 user=Depends(require_permission("document.read"))):
    document = repo(db, user).document(document_id)
    if not document:
        audit_cross_user_lookup(db, user, Document, document_id, "document")
        raise HTTPException(404, "Document not found")
    return {"document": {
        "id": document.id,
        "filename": document.filename,
        "document_type": document.document_type,
        "status": document.status,
    }}
@app.get("/api/audit-log")
def audit_log(limit: int=10, offset: int=0, event: str|None=None,
              db=Depends(get_db),user=Depends(require_permission("audit.read"))):
    limit=max(1,min(limit,100))
    offset=max(0,offset)
    return {"entries":[{"id":x.id,"timestamp":x.timestamp.isoformat(),"event":x.event,"details":x.details}
                       for x in repo(db,user).audit(limit=limit,offset=offset,event=event)]}
from .security.router import router as security_router; app.include_router(security_router)
