"""Terminal editor for explicit ordered New Kids release plans."""

from dataclasses import dataclass

from rich.console import Console
from rich.progress import Progress

from spotify_manager.application.ports.new_kids_plans import ReleasePlanDraft
from spotify_manager.application.ports.new_kids_plans import ReleasePlanSubmission
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.new_kids_plans import default_plan_release
from spotify_manager.interfaces.cli.display import ConsoleDisplay
from spotify_manager.interfaces.cli.terminal import TerminalPrompt


def _ordered_ids(text: str, releases: tuple[RankedRelease, ...]) -> tuple[str, ...]:
    positions = [int(value) for value in text.replace(",", " ").split()]
    if not positions or any(not 1 <= value <= len(releases) for value in positions):
        raise ValueError("Enter release numbers in listening order.")
    return tuple(releases[position - 1].spotify_id for position in positions)


def _visible(draft: ReleasePlanDraft) -> tuple[RankedRelease, ...]:
    result = []
    for release in draft.releases:
        if (
            default_plan_release(release)
            or release.spotify_id == draft.current_release_id
        ):
            result.append(release)
    return tuple(result)


@dataclass(frozen=True)
class NewKidsPlanCLI:
    """Own terminal display and confirmation while the regular progress is stopped.

    Args:
        console: Command-owned output.
        progress: Active command progress display, when present.
        display: Existing table and prompt resources.
    """

    console: Console
    progress: Progress | None
    display: ConsoleDisplay

    async def choose_plan(self, draft: ReleasePlanDraft) -> ReleasePlanSubmission:
        """Read a distinct ordered selection with explicit shorter-plan confirmation.

        Args:
            draft: Complete discography and transfer context.

        Returns:
            Accepted order or a skip/quit decision.
        """
        if self.progress is not None:
            self.progress.stop()
        try:
            return await self._read(draft)
        finally:
            if self.progress is not None:
                self.progress.start()

    async def _read(self, draft: ReleasePlanDraft) -> ReleasePlanSubmission:
        releases = _visible(draft)
        while True:
            self._show(draft, releases)
            response = await TerminalPrompt(self.display.prompt).ask(
                "Release numbers in order; all: show every category; s: skip; q: quit",
                console=self.console,
            )
            if response.strip().casefold() == "all":
                releases = draft.releases
                continue
            if response.strip().casefold() in {"s", "q"}:
                return ReleasePlanSubmission(
                    "skip" if response.strip().casefold() == "s" else "quit"
                )
            try:
                identities = _ordered_ids(response, releases)
            except ValueError as exc:
                self.console.print(str(exc), markup=False)
                continue
            if await self._confirm(identities, releases):
                answer = await self._resolved(draft, identities)
                if answer is not None:
                    return answer

    async def _resolved(
        self, draft: ReleasePlanDraft, identities: tuple[str, ...]
    ) -> ReleasePlanSubmission | None:
        short = len(identities) < 4
        if not draft.migration or draft.current_release_id:
            return ReleasePlanSubmission(
                "select", identities, short, draft.current_release_id
            )
        choices = [str(index) for index in range(1, len(identities) + 1)]
        position = await TerminalPrompt(self.display.prompt).ask(
            "Current album's position in the selected order",
            choices=choices,
            console=self.console,
        )
        confirm = await TerminalPrompt(self.display.prompt).ask(
            "Confirm this edition contains the current track",
            choices=["yes", "no"],
            default="no",
            console=self.console,
        )
        if confirm != "yes":
            return None
        return ReleasePlanSubmission(
            "select", identities, short, identities[int(position) - 1], True
        )

    def _show(
        self, draft: ReleasePlanDraft, releases: tuple[RankedRelease, ...]
    ) -> None:
        self.console.print(f"Release plan for {draft.artist}", markup=False)
        context = (
            f"Current album: {draft.queue_album}; "
            f"current track: {draft.current_track}. "
            "Include this album; earlier entries count as completed."
            if draft.migration
            else f"Queue 2 album: {draft.queue_album}. "
            "Choose it explicitly to include it."
        )
        self.console.print(context, markup=False)
        if draft.notice:
            self.console.print(draft.notice, markup=False)
        table = self.display.create_table(title="Choose up to four releases")
        for label in ("#", "Release", "Type", "Date"):
            table.add_column(label)
        for index, release in enumerate(releases, 1):
            table.add_row(
                str(index), release.name, release.release_type, release.release_date
            )
        self.console.print(table)

    async def _confirm(
        self, identities: tuple[str, ...], releases: tuple[RankedRelease, ...]
    ) -> bool:
        names = {release.spotify_id: release.name for release in releases}
        self.console.print(
            " → ".join(names[identity] for identity in identities), markup=False
        )
        label = (
            "Confirm this shorter plan" if len(identities) < 4 else "Confirm this order"
        )
        answer = await TerminalPrompt(self.display.prompt).ask(
            label, choices=["yes", "no"], default="no", console=self.console
        )
        return answer == "yes"
