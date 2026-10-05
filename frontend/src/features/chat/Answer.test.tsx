/**
 * Citation rendering tests.
 *
 * These guard the product's core promise at the UI layer: a `[1]` in the prose must be a real,
 * clickable reference to a real retrieved passage, and a reference the server did not resolve
 * must never become a dead chip pointing at nothing.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { Citation } from "../../lib/api";
import { AnswerBody, SourcePanel } from "./Answer";

function citation(overrides: Partial<Citation> = {}): Citation {
  return {
    document: "02_source_of_wealth_verification_guidelines.md",
    chunk: "Payslips for the most recent three consecutive months are required.",
    index: 1,
    document_id: "doc_1",
    document_title: "Source of Wealth Verification Guidelines",
    version: "1.3",
    effective_date: "2025-03-01",
    section: "3. Documentation Requirements by Category",
    subsection: "3.1 Employment / Salary",
    page: null,
    chunk_uid: "f2e402da91cebaa9",
    label: "Source of Wealth Verification Guidelines v1.3 — §3.1 Employment / Salary",
    retrieval_score: 0.032,
    rerank_score: 5.1,
    ...overrides,
  } as Citation;
}

describe("AnswerBody", () => {
  it("renders a [1] reference as a clickable citation chip", async () => {
    const onClick = vi.fn();
    render(
      <AnswerBody
        content="Three documents are required [1]."
        citations={[citation()]}
        onCitationClick={onClick}
      />,
    );

    const chip = screen.getByRole("button", { name: /View source 1/i });
    expect(chip).toBeInTheDocument();
    await userEvent.click(chip);
    expect(onClick).toHaveBeenCalledWith(expect.objectContaining({ index: 1 }));
  });

  it("leaves an unresolved reference as plain text rather than a dead chip", () => {
    render(
      <AnswerBody content="A claim [7] with no matching citation." citations={[citation()]} onCitationClick={vi.fn()} />,
    );
    // Only citation 1 exists, so [7] must not become a button.
    expect(screen.queryByRole("button", { name: /View source 7/i })).not.toBeInTheDocument();
    expect(screen.getByText(/with no matching citation/)).toBeInTheDocument();
  });

  it("renders GFM tables, which policy answers rely on", () => {
    const markdown = [
      "| Risk Band | Review |",
      "| --- | --- |",
      "| Low | 24 months |",
      "| High | 6 months |",
    ].join("\n");

    render(<AnswerBody content={markdown} citations={[]} onCitationClick={vi.fn()} />);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Risk Band" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "6 months" })).toBeInTheDocument();
  });

  it("renders chips inside list items as well as paragraphs", async () => {
    render(
      <AnswerBody
        content={"- Payslips are required [1]\n- Bank statements are required [1]"}
        citations={[citation()]}
        onCitationClick={vi.fn()}
      />,
    );
    expect(screen.getAllByRole("button", { name: /View source 1/i })).toHaveLength(2);
  });
});

describe("SourcePanel", () => {
  it("shows full provenance and the exact retrieved passage", () => {
    render(
      <MemoryRouter>
        <SourcePanel citation={citation()} onClose={vi.fn()} />
      </MemoryRouter>,
    );

    expect(screen.getByText("Source of Wealth Verification Guidelines")).toBeInTheDocument();
    expect(screen.getByText("v1.3")).toBeInTheDocument();
    expect(screen.getByText("2025-03-01")).toBeInTheDocument();
    expect(screen.getByText("3.1 Employment / Salary")).toBeInTheDocument();
    expect(
      screen.getByText(/Payslips for the most recent three consecutive months/),
    ).toBeInTheDocument();
  });

  it("states that a page number is not applicable rather than inventing one", () => {
    render(
      <MemoryRouter>
        <SourcePanel citation={citation({ page: null })} onClose={vi.fn()} />
      </MemoryRouter>,
    );
    expect(screen.getByText(/not applicable/i)).toBeInTheDocument();
  });

  it("renders nothing when no citation is selected", () => {
    const { container } = render(
      <MemoryRouter>
        <SourcePanel citation={null} onClose={vi.fn()} />
      </MemoryRouter>,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
