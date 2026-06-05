"""Minimal demo for the active preference architecture."""

from __future__ import annotations

import json
from pathlib import Path

from active_preference import ActivePreferenceSystem, SyntheticPreferenceGenerator


def main() -> None:
    output_dir = Path("json")
    output_dir.mkdir(exist_ok=True)

    generator = SyntheticPreferenceGenerator(seed=11)
    profiles = generator.generate_profiles(count=5)
    dataset_path = generator.save_jsonl(profiles, output_dir / "synthetic_preference_training.jsonl")

    system = ActivePreferenceSystem(stop_threshold=0.65, min_turns=3)
    example_answers = profiles[0].statements

    transcript = []
    for answer in example_answers:
        question = system.next_question()
        result = system.answer(answer)
        transcript.append(
            {
                "question": question,
                "answer": answer,
                "ready_for_optimization": result["ready_for_optimization"],
            }
        )

    weights_path = system.export_solver_weights(output_dir / "active_preference_weights_example.json")
    state_path = output_dir / "active_preference_state_example.json"
    state_path.write_text(
        json.dumps(
            {
                "training_dataset": str(dataset_path),
                "solver_weights": str(weights_path),
                "transcript": transcript,
                "state": system.tracker.state.to_dict(),
            },
            ensure_ascii=False,
            indent=4,
        ),
        encoding="utf-8",
    )

    print(f"Synthetic training data: {dataset_path}")
    print(f"Solver-compatible weights: {weights_path}")
    print(f"Demo state: {state_path}")


if __name__ == "__main__":
    main()
