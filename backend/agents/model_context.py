from backend.schemas import ModelContextPacket, ReportDraft


def build_model_context_packet(report: ReportDraft) -> ModelContextPacket:
    observed_inputs = [
        f"{item.kind}: {item.value}" for item in report.collected_inputs
    ]
    inferred_context = [
        f"{item.label}: {item.value} ({round(item.confidence * 100)}% confidence)"
        for item in report.inferred_context
    ]

    return ModelContextPacket(
        report_id=report.id,
        task="draft_311_service_request",
        model_role=(
            "Civic intake report agent that turns resident observations into a "
            "reviewable 311 service-request draft."
        ),
        prompt_goal=(
            "Produce or refine a structured 311 report while preserving what was "
            "observed, what was inferred, what historical context suggests, and "
            "what still requires human review."
        ),
        observed_inputs=observed_inputs,
        inferred_context=inferred_context,
        civic_evidence=report.civic_context,
        routing_context=report.routing,
        uncertainty=report.uncertainty,
        required_human_confirmations=report.human_review,
        output_requirements=[
            "Keep resident-observed facts separate from model inferences.",
            "Preserve exact-location confirmation as a required review item until confirmed.",
            "Include pedestrian-safety context when flooding affects a school crossing.",
            "Use historical 311 context as advisory evidence, not proof of the current issue.",
            "Return a concise title, service category, narrative, routing suggestion, uncertainty, and follow-up questions.",
        ],
        guardrails=[
            "Do not claim that historical 311 records verify the current condition.",
            "Do not submit or imply submission before resident confirmation.",
            "Do not invent a precise location, agency rule, or service endpoint.",
            "Prefer asking a follow-up question when location, severity, or obstruction is uncertain.",
            "Avoid retaining raw media or raw historical rows in the prompt packet.",
        ],
        dtpr_disclosures=[step.id for step in report.dtpr_chain],
    )
