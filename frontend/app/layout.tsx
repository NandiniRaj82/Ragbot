import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "RAGBot — AI Video Analytics",
  description:
    "Compare any YouTube and Instagram video with AI-powered RAG analysis. Get engagement insights, transcript-grounded answers, and actionable content strategy.",
  keywords: [
    "social media analytics",
    "RAG chatbot",
    "video comparison",
    "YouTube analytics",
    "Instagram analytics",
    "AI content strategy",
    "Gemini",
  ],
  openGraph: {
    title: "RAGBot — AI Video Analytics",
    description: "AI-powered social media video analytics with transcript RAG",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={inter.variable}>
      <body>{children}</body>
    </html>
  );
}
