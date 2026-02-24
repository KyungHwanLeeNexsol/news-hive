'use client';

export default function LoadingBar({ loading }: { loading: boolean }) {
  if (!loading) return null;
  return (
    <div className="flex flex-col items-center justify-center py-24">
      <div className="w-8 h-8 border-[3px] border-[#e5e5e5] border-t-[#1261c4] rounded-full animate-spin" />
      <p className="mt-3 text-[13px] text-[#999]">불러오는 중...</p>
    </div>
  );
}
