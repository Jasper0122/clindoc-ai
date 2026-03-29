# backend/alignment_engine.py
# 兼容：把 backend 目录加入 sys.path，以便本地导入可以工作
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from typing import Optional, Dict, Any, List
import dataclasses
import logging
from types import SimpleNamespace

from pdf_section_parser import parse_pdf_sections
from criteria_extractor import extract_criteria
from clinical_extractor import extract_clinical_data
from criteria_evaluator import evaluate_criteria
from justification_builder import build_justification
from admission_scorer import compute_admission_decision

try:
    from mcg_criteria import MCG_CRITERIA, MCG_CRITERIA_MAP
except Exception:
    MCG_CRITERIA = None
    MCG_CRITERIA_MAP = {}

try:
    from alignment_types import ClinicalData as ClinicalDataDC
except Exception:
    ClinicalDataDC = None

logger = logging.getLogger("clindocai.alignment_engine")
logger.setLevel(logging.INFO)


def _clinicaldict_to_dataclass(d: Dict[str, Any]):
    if ClinicalDataDC:
        try:
            return ClinicalDataDC(
                age=d.get("age"),
                symptoms=d.get("symptoms"),
                vitals=d.get("vitals"),
                labs=d.get("labs"),
                imagingFindings=d.get("imagingFindings"),
                oxygenRequirement=d.get("oxygenRequirement", False),
                hypoxemia=d.get("hypoxemia", False),
                comorbidities=d.get("comorbidities"),
                outpatientFailure=d.get("outpatientFailure", False),
            )
        except Exception:
            pass
    # fallback SimpleNamespace
    return SimpleNamespace(**{
        "age": d.get("age"),
        "symptoms": d.get("symptoms"),
        "vitals": d.get("vitals"),
        "labs": d.get("labs"),
        "imagingFindings": d.get("imagingFindings"),
        "oxygenRequirement": d.get("oxygenRequirement", False),
        "hypoxemia": d.get("hypoxemia", False),
        "comorbidities": d.get("comorbidities", []),
        "outpatientFailure": d.get("outpatientFailure", False),
    })


def _mcg_criteria_to_objs() -> List[Any]:
    out = []
    if not MCG_CRITERIA:
        return out
    for c in MCG_CRITERIA:
        try:
            out.append(SimpleNamespace(
                id=c.get("id"),
                text=c.get("text"),
                category=c.get("category"),
                keywords=c.get("keywords", [])
            ))
        except Exception:
            out.append(SimpleNamespace(id=c.get("id"), text=c.get("text"), category=c.get("category")))
    return out


def _to_plain_dict(evaluated_item: Any) -> Dict[str, Any]:
    try:
        out = dataclasses.asdict(evaluated_item)
    except Exception:
        if isinstance(evaluated_item, dict):
            out = dict(evaluated_item)
        else:
            out = {
                "criterionId": getattr(evaluated_item, "criterionId", None) or getattr(evaluated_item, "id", None),
                "criterionText": getattr(evaluated_item, "criterionText", None) or getattr(evaluated_item, "text", None),
                "category": getattr(evaluated_item, "category", None),
                "status": getattr(evaluated_item, "status", None),
                "evidenceFound": getattr(evaluated_item, "evidenceFound", None) or "",
                "suggestedLanguage": getattr(evaluated_item, "suggestedLanguage", None) or "",
                "scoreContribution": getattr(evaluated_item, "scoreContribution", 0) or 0,
            }
    # normalize some fields
    out["criterionId"] = out.get("criterionId")
    out["criterionText"] = out.get("criterionText") or ""
    out["category"] = out.get("category") or None
    out["status"] = out.get("status") or "Missing"
    out["evidenceFound"] = out.get("evidenceFound", "") or ""
    out["suggestedLanguage"] = out.get("suggestedLanguage", "") or ""
    out["scoreContribution"] = int(out.get("scoreContribution", 0) or 0)
    return out


def _criterion_to_dict(c: Any) -> Dict[str, Any]:
    try:
        return dataclasses.asdict(c)
    except Exception:
        if isinstance(c, dict):
            return dict(c)
        else:
            return {
                "id": getattr(c, "id", None),
                "text": getattr(c, "text", None),
                "category": getattr(c, "category", None),
            }


def _short_action_for_criterion(c: Dict[str, Any]) -> str:
    try:
        # c might be dict-like or SimpleNamespace
        if isinstance(c, dict):
            if c.get("action"):
                return c.get("action")
            return c.get("text", "")[:120]
        else:
            if getattr(c, "action", None):
                return getattr(c, "action")
            return (getattr(c, "text", "") or "")[:120]
    except Exception:
        return (str(c.get("text") if isinstance(c, dict) else getattr(c, "text", "")) or "")[:120]


def _normalize_status_for_filter(s: Optional[str]) -> str:
    if not s:
        return ""
    return str(s).strip().lower()


def _match_evaluated_to_criteria(evaluated_dicts: List[Dict[str, Any]], canonical_criteria: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Build a mapping from canonical criterion id -> evaluated dict.
    If evaluator didn't return an entry for a canonical id, fill with Missing default.
    """
    eval_map: Dict[str, Dict[str, Any]] = {}

    by_id = {}
    by_textstart = {}
    for ed in evaluated_dicts:
        cid = ed.get("criterionId")
        ctext = ed.get("criterionText") or ""
        if cid:
            by_id[str(cid)] = ed
        if ctext:
            by_textstart[ctext.strip()[:40]] = ed

    for c in canonical_criteria:
        cid = c.get("id")
        ctext = c.get("text") or ""
        found = None
        if cid and str(cid) in by_id:
            found = by_id[str(cid)]
        else:
            start = str(ctext)[:40]
            if start in by_textstart:
                found = by_textstart[start]
            else:
                for k, v in by_textstart.items():
                    if k and k in (ed_text := (v.get("criterionText") or "")):
                        found = v
                        break
        if found:
            ed_norm = {
                "criterionId": found.get("criterionId") or cid,
                "criterionText": found.get("criterionText") or ctext,
                "category": found.get("category") or c.get("category"),
                "status": found.get("status") or "Missing",
                "evidenceFound": found.get("evidenceFound", "") or "",
                "suggestedLanguage": found.get("suggestedLanguage", "") or "",
                "scoreContribution": int(found.get("scoreContribution", 0) or 0)
            }
            eval_map[str(cid)] = ed_norm
        else:
            # default Missing entry
            eval_map[str(cid)] = {
                "criterionId": cid,
                "criterionText": ctext,
                "category": c.get("category"),
                "status": "Missing",
                "evidenceFound": "",
                "suggestedLanguage": "",
                "scoreContribution": 0
            }

    return eval_map


def run_alignment_engine(doctor_notes: str, pdf_text: Optional[str] = "") -> Dict[str, Any]:
    # 1) parse sections
    try:
        sections = parse_pdf_sections(pdf_text or "")
    except Exception as ex:
        logger.exception("PDF parsing failed: %s", ex)
        sections = {}

    # 2) load canonical criteria (always prefer canonical)
    criteria_objs = []
    used_mcg = False
    if MCG_CRITERIA:
        try:
            criteria_objs = _mcg_criteria_to_objs()
            used_mcg = True
            logger.info("Using canonical MCG_CRITERIA (count=%d).", len(criteria_objs))
        except Exception as ex:
            logger.exception("Failed to load MCG_CRITERIA as objects: %s", ex)
            criteria_objs = []
    else:
        # fallback to extractor (but we want canonical ideally)
        try:
            criteria_objs = extract_criteria(sections or {})
            logger.info("extract_criteria returned %d items", len(criteria_objs))
        except Exception as ex:
            logger.exception("extract_criteria failed: %s", ex)
            criteria_objs = []

    logger.info("Extracted criteria count (final): %d (used_mcg=%s)", len(criteria_objs), used_mcg)

    # 3) extract clinical data
    try:
        clinical_data_dict = extract_clinical_data(doctor_notes or "")
    except Exception as ex:
        logger.exception("extract_clinical_data failed: %s", ex)
        clinical_data_dict = {}

    # 4) evaluate canonical criteria
    try:
        evaluated = evaluate_criteria(criteria_objs or [], clinical_data_dict or {})
    except Exception as ex:
        logger.exception("evaluate_criteria failed: %s", ex)
        evaluated = []

    # 5) convert evaluated -> plain dicts
    evaluated_dicts = []
    for e in evaluated or []:
        try:
            evaluated_dicts.append(_to_plain_dict(e))
        except Exception:
            try:
                # best-effort fallback
                evaluated_dicts.append({
                    "criterionId": getattr(e, "criterionId", None) or getattr(e, "id", None),
                    "criterionText": getattr(e, "criterionText", None) or getattr(e, "text", None),
                    "category": getattr(e, "category", None),
                    "status": getattr(e, "status", None) or "Missing",
                    "evidenceFound": getattr(e, "evidenceFound", None) or "",
                    "suggestedLanguage": getattr(e, "suggestedLanguage", None) or "",
                    "scoreContribution": getattr(e, "scoreContribution", 0) or 0,
                })
            except Exception:
                continue

    logger.info("Evaluated items count: %d", len(evaluated_dicts))

    # 6) prepare canonical extractedCriteria JSON (stable order)
    criteria_json = []
    for c in criteria_objs or []:
        try:
            cid = getattr(c, "id", None) if not isinstance(c, dict) else c.get("id")
            ctext = getattr(c, "text", None) if not isinstance(c, dict) else c.get("text")
            ccat = getattr(c, "category", None) if not isinstance(c, dict) else c.get("category")
            criteria_json.append({
                "id": cid,
                "text": ctext,
                "category": ccat
            })
        except Exception:
            logger.exception("criterion -> dict conversion failed for: %s", str(c))
            try:
                criteria_json.append(dict(c))
            except Exception:
                criteria_json.append({"id": None, "text": None, "category": None})

    # 7) align evaluated items to canonical criteria (guarantee one entry per canonical id)
    canonical_list_for_map = criteria_json  # list of dicts with id/text
    eval_map = _match_evaluated_to_criteria(evaluated_dicts, canonical_list_for_map)

    # 8) Ensure each canonical criterion has an evaluation (stable order)
    aligned_evaluated_dicts = []
    for c in canonical_list_for_map:
        cid = str(c.get("id"))
        aligned_evaluated_dicts.append(eval_map.get(cid, {
            "criterionId": cid,
            "criterionText": c.get("text"),
            "category": c.get("category"),
            "status": "Missing",
            "evidenceFound": "",
            "suggestedLanguage": "",
            "scoreContribution": 0
        }))

    # 9) compute admission decision using evaluator results (scorer expects list of dict-like)
    try:
        decision = compute_admission_decision(aligned_evaluated_dicts)
    except Exception as ex:
        logger.exception("compute_admission_decision failed: %s", ex)
        decision = {"totalScore": 0, "maxPossibleScore": 0, "percentage": 0, "admissionRecommended": False}

    # 10) build justification / revised notes (use original evaluated objects if possible)
    try:
        clinical_dc = _clinicaldict_to_dataclass(clinical_data_dict or {})
        # build_justification expects clinical dataclass and evaluated items (we pass aligned_evaluated_dicts as list of dicts)
        revised_notes = build_justification(clinical_dc, aligned_evaluated_dicts or [], decision)
        if isinstance(revised_notes, str):
            revised_notes = {"clinicalSummary": revised_notes, "medicalNecessityJustification": "", "riskStratification": "", "conclusion": ""}
        if revised_notes is None:
            revised_notes = {"clinicalSummary": "", "medicalNecessityJustification": "", "riskStratification": "", "conclusion": ""}
    except Exception as ex:
        logger.exception("build_justification failed: %s", ex)
        revised_notes = {"clinicalSummary": "", "medicalNecessityJustification": "", "riskStratification": "", "conclusion": ""}

    # 11) Build the stable missingCriteria JSON: one entry per canonical criterion (you wanted NO 'evidence' field)
    missing_criteria_json = []
    for c in canonical_list_for_map:
        cid = str(c.get("id"))
        ed = eval_map.get(cid) or {
            "criterionId": cid,
            "criterionText": c.get("text"),
            "category": c.get("category"),
            "status": "Missing",
            "scoreContribution": 0
        }
        # normalize status
        st = _normalize_status_for_filter(str(ed.get("status", "") or ""))
        status_norm = "Missing"
        if st in ("met", "yes", "true", "satisfied"):
            status_norm = "Met"
        elif st in ("partial", "partially met", "partially", "partial match"):
            status_norm = "Partial"
        else:
            status_norm = "Missing"

        missing_criteria_json.append({
            "criterionId": cid,
            "guideline": c.get("text"),
            "action": _short_action_for_criterion(c),
            "status": status_norm,
            "scoreContribution": int(ed.get("scoreContribution", 0) or 0)
        })

    # 12) prepare revisedNoteText (compact)
    try:
        cs = revised_notes.get("clinicalSummary", "") or ""
        mj = revised_notes.get("medicalNecessityJustification", "") or ""
        risk = revised_notes.get("riskStratification", "") or ""
        concl = revised_notes.get("conclusion", "") or ""
        revised_text_parts = [p.strip() for p in [cs, mj, risk, concl] if p and p.strip()]
        revised_text = "\n\n".join(revised_text_parts)
    except Exception:
        revised_text = ""

    # Final returned payload (JSON-serializable)
    return {
        "extractedCriteria": criteria_json,              # canonical list (stable)
        "revisedNotes": revised_notes,
        "revisedNoteText": revised_text,
        # return ALL canonical criteria with their status and concise action/guideline to keep UI stable
        "missingCriteria": missing_criteria_json,
        "overallScore": decision.get("percentage", 0),
        "admissionRecommended": decision.get("admissionRecommended", False),
        "rawPdfSectionsPreview": (str(sections)[:8000] if sections else ""),
        "_rawSections": sections,
        "_rawEvaluatedPreview": evaluated_dicts[:20],
        "_rawDecision": decision,
        "usedCanonicalMCG": bool(used_mcg),
    }