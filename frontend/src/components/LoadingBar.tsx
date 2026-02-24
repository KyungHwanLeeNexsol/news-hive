'use client';

export default function LoadingBar({ loading }: { loading: boolean }) {
  if (!loading) return null;
  return (
    <div className="fixed top-0 left-0 right-0 z-50 h-[3px] bg-[#e5e5e5] overflow-hidden">
      <div className="h-full bg-[#1261c4] animate-progress" />
    </div>
  );
}
