import argparse
import json
import sys
from typing import Any

from find_my_next_book_api.agents.runtime import (
    AgentConfigurationError,
    create_live_workflow,
)
from find_my_next_book_api.agents.workflow import RecommendationState, initial_state
from find_my_next_book_api.core.settings import get_agent_settings
from find_my_next_book_api.persistence.session_store import SessionStore

SMOKE_TEST_REQUEST = "推荐一些已完结的古言权谋小说，女主聪明，不要虐文"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m find_my_next_book_api.cli",
        description="Run the personalized, evidence-grounded NovelScout graph.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    recommend = subparsers.add_parser("recommend", help="Run a live recommendation request")
    recommend.add_argument("request", help="Chinese natural-language reading preferences")
    recommend.add_argument("--session", help="Load and update this local taste-profile ID")
    recommend.add_argument(
        "--feedback",
        help="Feedback to merge into the structured profile, e.g. 感情线还是太多",
    )
    recommend.add_argument(
        "--read",
        action="append",
        default=[],
        metavar="TITLE",
        help="Mark a title as already read; repeat for multiple books",
    )
    recommend.add_argument("--verbose", action="store_true", help="Print graph events live")

    smoke = subparsers.add_parser(
        "smoke-test", help="Run the built-in live Gemini + Tavily request"
    )
    smoke.add_argument("--verbose", action="store_true")

    profile = subparsers.add_parser("profile", help="Inspect a local structured profile")
    profile.add_argument("session", help="Local profile ID")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_agent_settings()
    store = SessionStore(settings.agent_session_dir)

    if args.command == "profile":
        try:
            record = store.load(args.session)
        except (OSError, ValueError) as exc:
            print(f"Could not read profile: {exc}", file=sys.stderr)
            return 2
        if record is None:
            print(f"No local profile exists for session '{args.session}'.")
            return 1
        print(json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return 0

    request = args.request if args.command == "recommend" else SMOKE_TEST_REQUEST
    session_id = args.session if args.command == "recommend" else None
    feedback = args.feedback if args.command == "recommend" else None
    already_read = args.read if args.command == "recommend" else []

    try:
        existing = store.load(session_id) if session_id else None
        runtime = create_live_workflow(settings)
        final_state = _run_graph(
            runtime.graph,
            request,
            verbose=args.verbose,
            existing_profile=existing.profile if existing else None,
            feedback=feedback,
            already_read=already_read,
        )
        if session_id and final_state["profile"] and not final_state["fatal_error"]:
            store.save(
                session_id,
                final_state["profile"],
                [item.title for item in final_state["recommendations"]],
            )
    except AgentConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        print(
            "Copy the repository .env.example to .env and set GOOGLE_API_KEY and TAVILY_API_KEY.",
            file=sys.stderr,
        )
        return 2
    except (OSError, ValueError) as exc:
        print(f"Session error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Recommendation run cancelled.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Recommendation workflow failed: {exc}", file=sys.stderr)
        return 1

    _print_report(final_state, runtime.model_name, runtime.search_provider_name)
    if session_id and not final_state["fatal_error"]:
        print(f"\nStructured taste profile saved as local session: {session_id}")
    return 1 if final_state["fatal_error"] else 0


def _run_graph(
    graph: Any,
    request: str,
    *,
    verbose: bool,
    existing_profile=None,
    feedback: str | None = None,
    already_read: list[str] | None = None,
) -> RecommendationState:
    final_state = initial_state(
        request,
        existing_profile=existing_profile,
        feedback=feedback,
        already_read=already_read,
    )
    emitted_trace_count = 0
    for snapshot in graph.stream(
        final_state,
        stream_mode="values",
        config={"recursion_limit": 24},
    ):
        final_state = snapshot
        if verbose:
            for event in snapshot["trace"][emitted_trace_count:]:
                print(f"[graph] {event.node} · {event.action}: {event.detail}")
            emitted_trace_count = len(snapshot["trace"])
    return final_state


def _print_report(state: RecommendationState, model_name: str, search_provider_name: str) -> None:
    print("\n=== Providers ===")
    print(f"LLM: {model_name}")
    print(f"Search tool: {search_provider_name}")

    print("\n=== Structured reader taste profile ===")
    if state["profile"]:
        print(json.dumps(state["profile"].model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        print("Unavailable")

    print("\n=== Resolved reference novels ===")
    if not state["references"]:
        print("No reference novels supplied.")
    for book in state["references"]:
        print(
            f"- {book.title} · {book.author or '作者未确认'} · "
            f"verification={book.verification_status.value}"
        )
        if book.official_url:
            print(f"  Official: {book.official_url}")
        for uncertainty in book.uncertainties:
            print(f"  Uncertain: {uncertainty}")

    print("\n=== Graph nodes and tools ===")
    for event in state["trace"]:
        print(f"- {event.node} · {event.action}: {event.detail}")

    print("\n=== Search queries executed ===")
    if not state["executions"]:
        print("No search queries ran.")
    for execution in state["executions"]:
        domains = (
            f" domains={','.join(execution.include_domains)}" if execution.include_domains else ""
        )
        status = (
            f"error={execution.error}" if execution.error else f"results={execution.result_count}"
        )
        print(f"- [{execution.stage.value}] {execution.query}{domains} ({status})")

    print("\n=== Extracted and verified candidates ===")
    if not state["verified_candidates"]:
        print("No candidates reached verification.")
    for book in state["verified_candidates"]:
        print(
            f"- {book.title} · {book.author or '作者未确认'} · "
            f"{book.verification_status.value} · status={book.publication_status.value}"
        )
        if book.official_url:
            print(f"  Official: {book.official_url}")
        if book.genre_tags:
            print(f"  Objective tags: {', '.join(book.genre_tags)}")
        for opinion in book.reader_opinions:
            print(f"  Reader opinion [{', '.join(opinion.source_ids)}]: {opinion.text}")

    print("\n=== Final grounded recommendations ===")
    if not state["recommendations"]:
        print("No candidates met the current evidence and hard-filter threshold.")
    for recommendation in state["recommendations"]:
        print(
            f"\n{recommendation.rank}. {recommendation.title} · "
            f"{recommendation.author or '作者未确认'} · "
            f"{recommendation.platform or '平台未确认'} · "
            f"verification={recommendation.verification_status.value} · "
            f"status={recommendation.publication_status.value} · "
            f"score={recommendation.relevance_score:.1f}/100"
        )
        if recommendation.official_url:
            print(f"   Original platform: {recommendation.official_url}")
        for reason in recommendation.match_reasons:
            print(f"   Why: {reason}")
        for source in recommendation.sources:
            print(f"   Evidence [{source.source_id}]: {source.url}")
        for uncertainty in recommendation.uncertainties:
            print(f"   Uncertain: {uncertainty}")

    print("\n=== Evaluation metrics ===")
    if state["metrics"]:
        print(json.dumps(state["metrics"].model_dump(mode="json"), indent=2))
    else:
        print("Unavailable because the workflow stopped before ranking.")

    if state["errors"]:
        print("\n=== Errors and warnings ===")
        for error in state["errors"]:
            print(f"- {error}")


if __name__ == "__main__":
    raise SystemExit(main())
