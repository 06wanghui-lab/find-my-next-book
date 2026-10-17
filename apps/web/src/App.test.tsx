import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const successfulResponse = {
  profile: {
    genres: ["BL", "无限流"],
    desired_traits: ["主角聪明"],
    positive_aspects: ["副本烧脑", "群像出色"],
    hard_exclusions: ["感情线盖过剧情"],
    publication_status: "any",
  },
  recommendations: [
    {
      rank: 1,
      title: "测试小说",
      author: "测试作者",
      platform: "晋江文学城",
      publication_status: "completed",
      relevance_score: 91.4,
      match_reasons: ["已核实为无限流，副本设计与用户偏好相符。"],
      uncertainties: ["甜虐程度来自读者评论，具有主观性。"],
      sources: [
        {
          source_id: "S1",
          title: "测试小说_晋江文学城",
          url: "https://www.jjwxc.net/onebook.php?novelid=1",
          excerpt: "测试证据",
        },
      ],
      official_url: "https://www.jjwxc.net/onebook.php?novelid=1",
      verification_status: "official",
      genre_tags: ["无限流", "纯爱"],
      reasons: [
        {
          text: "已核实为无限流，副本设计与用户偏好相符。",
          kind: "verified_metadata",
          source_ids: ["S1"],
        },
      ],
    },
  ],
  warnings: [],
  providers: { model: "Mock Gemini", search: "Mock Tavily" },
};

function mockJsonResponse(payload: unknown, ok = true, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok,
      status,
      json: vi.fn().mockResolvedValue(payload),
    }),
  );
}

describe("App", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("explains the grounded discovery promise", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: /下一本喜欢的小说/ }),
    ).toBeInTheDocument();
    expect(screen.getByText(/宁可少一点，也不编一本/)).toBeInTheDocument();
  });

  it("posts the request and renders grounded recommendation cards", async () => {
    mockJsonResponse(successfulResponse);
    render(<App />);

    fireEvent.change(screen.getByLabelText("今天想读什么？"), {
      target: { value: "想看烧脑的 BL 无限流，群像要好" },
    });
    fireEvent.click(screen.getByRole("button", { name: "帮我找下一本" }));

    expect(screen.getByText(/正在理解口味/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("测试小说")).toBeInTheDocument());

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/recommend",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ request: "想看烧脑的 BL 无限流，群像要好" }),
      }),
    );
    expect(screen.getByText(/测试作者.*晋江文学城.*已完结/)).toBeInTheDocument();
    expect(screen.getByText("官方页面已确认")).toBeInTheDocument();
    expect(screen.getByText("已核实")).toBeInTheDocument();
    expect(screen.getByText("91")).toBeInTheDocument();
    expect(screen.getByText(/副本设计与用户偏好相符/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /查看原始平台/ })).toHaveAttribute(
      "href",
      "https://www.jjwxc.net/onebook.php?novelid=1",
    );
  });

  it("shows a useful empty state when grounding removes every candidate", async () => {
    mockJsonResponse({ ...successfulResponse, recommendations: [] });
    render(<App />);

    fireEvent.change(screen.getByLabelText("今天想读什么？"), {
      target: { value: "非常冷门的小说要求" },
    });
    fireEvent.click(screen.getByRole("button", { name: "帮我找下一本" }));

    expect(
      await screen.findByText("这次没有足够可靠的推荐"),
    ).toBeInTheDocument();
  });

  it("surfaces Gemini quota errors without exposing backend details", async () => {
    mockJsonResponse(
      {
        detail: {
          code: "model_quota_exceeded",
          message: "AI 推荐额度暂时用完了，请稍后再试或配置可用的备用模型。",
        },
      },
      false,
      429,
    );
    render(<App />);

    fireEvent.change(screen.getByLabelText("今天想读什么？"), {
      target: { value: "想看古言权谋" },
    });
    fireEvent.click(screen.getByRole("button", { name: "帮我找下一本" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("AI 推荐额度暂时用完了");
  });
});

