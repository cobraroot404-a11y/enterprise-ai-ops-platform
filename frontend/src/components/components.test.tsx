import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ConfirmDialog from "./ConfirmDialog";
import { CitationList, ReviewBadge, TicketStateBadge, Timeline } from "./provenance";
import { Pager, SortHeader } from "./ui";

describe("ConfirmDialog", () => {
  it("renders nothing when closed and focuses Cancel when opened", () => {
    const { rerender } = render(<ConfirmDialog open={false} title="T" confirmLabel="Go" onConfirm={() => {}} onCancel={() => {}}>body</ConfirmDialog>);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    rerender(<ConfirmDialog open title="Approve?" confirmLabel="Go" onConfirm={() => {}} onCancel={() => {}}>body</ConfirmDialog>);
    expect(screen.getByRole("alertdialog", { name: "Approve?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  });

  it("confirms and cancels, and Escape cancels", async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<ConfirmDialog open title="X" confirmLabel="Do it" onConfirm={onConfirm} onCancel={onCancel}>body</ConfirmDialog>);
    await userEvent.click(screen.getByRole("button", { name: "Do it" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("disables both buttons while busy so a consequential action cannot be sent twice", () => {
    render(<ConfirmDialog open busy title="X" confirmLabel="Do it" onConfirm={() => {}} onCancel={() => {}}>body</ConfirmDialog>);
    expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  });
});

describe("workflow status vocabulary", () => {
  it("never shows an external action as successful without the backend's confirmation", () => {
    const { rerender } = render(<TicketStateBadge state="APPROVED" />);
    expect(screen.getByText("Approved · not yet submitted")).toBeInTheDocument();
    rerender(<TicketStateBadge state="SUBMITTED" externalId={null} />);
    expect(screen.getByText("Submitted (no external id)")).toBeInTheDocument();
    rerender(<TicketStateBadge state="SUBMITTED" externalId="MNT-1001" />);
    expect(screen.getByText("Submitted")).toBeInTheDocument();
    rerender(<TicketStateBadge state="RETRY_PENDING" />);
    expect(screen.getByText("Retry scheduled")).toBeInTheDocument();
    rerender(<TicketStateBadge state="FAILED" />);
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("distinguishes blocked, evidence-verified and human-reviewed incidents", () => {
    const { rerender } = render(<ReviewBadge status="needs_review" />);
    expect(screen.getByText("Blocked · human review required")).toBeInTheDocument();
    rerender(<ReviewBadge status="pending_review" />);
    expect(screen.getByText("Evidence verified · ready for a ticket")).toBeInTheDocument();
    rerender(<ReviewBadge status="accepted" />);
    expect(screen.getByText("Human-reviewed · accepted")).toBeInTheDocument();
  });
});

describe("evidence and history", () => {
  const citation = { marker: 1, chunk_id: "c-1", filename: "manual.pdf", version: 2, page_number: 3, record_id: null, quote: "Stop the pump above 7.1 mm/s" };

  it("labels citations as retrieved evidence with a verified verbatim quote and lets the user inspect them", async () => {
    render(<CitationList citations={[citation]} />);
    expect(screen.getByText("Retrieved evidence")).toBeInTheDocument();
    expect(screen.getByText("Verbatim quote verified")).toBeInTheDocument();
    expect(screen.queryByText("c-1")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Inspect" }));
    expect(screen.getByText("c-1")).toBeInTheDocument();
    expect(screen.getByLabelText("Citation 1 details")).toHaveTextContent("page 3");
  });

  it("shows an explicit empty state without citations", () => {
    render(<CitationList citations={[]} empty="No verified citations support this." />);
    expect(screen.getByText("No verified citations support this.")).toBeInTheDocument();
  });

  it("renders history with readable labels and the recorded justification", () => {
    render(<Timeline events={[{ id: 1, action: "incident.review_accept", actor: "sup@x.test", actor_type: "user", details: { comment: "Verified on site" }, created_at: "2026-01-01T10:00:00Z" }]} />);
    expect(screen.getByText("Human review: accepted")).toBeInTheDocument();
    expect(screen.getByText("Verified on site")).toBeInTheDocument();
  });
});

describe("tables", () => {
  it("exposes sort state to assistive technology", async () => {
    const onSort = vi.fn();
    render(<table><thead><tr><SortHeader column="priority" label="Priority" sort="priority" order="desc" onSort={onSort} /></tr></thead></table>);
    expect(screen.getByRole("columnheader")).toHaveAttribute("aria-sort", "descending");
    await userEvent.click(screen.getByRole("button", { name: "Sort by Priority" }));
    expect(onSort).toHaveBeenCalledWith("priority");
  });

  it("paginates with accessible controls and hides itself when everything fits", async () => {
    const onChange = vi.fn();
    const { rerender } = render(<Pager total={40} limit={15} offset={0} onChange={onChange} />);
    expect(screen.getByRole("navigation", { name: "Pagination" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onChange).toHaveBeenCalledWith(15);
    rerender(<Pager total={5} limit={15} offset={0} onChange={onChange} />);
    expect(screen.queryByRole("navigation", { name: "Pagination" })).toBeNull();
  });
});
