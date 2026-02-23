interface UpDownBarProps {
  rising: number;
  flat: number;
  falling: number;
}

export default function UpDownBar({ rising, flat, falling }: UpDownBarProps) {
  const total = rising + flat + falling;
  if (total === 0) {
    return <div className="h-[14px] w-full rounded bg-[#e8e8e8]" />;
  }

  const risingPct = (rising / total) * 100;
  const flatPct = (flat / total) * 100;
  const fallingPct = (falling / total) * 100;

  return (
    <div className="flex h-[14px] w-full overflow-hidden rounded">
      {risingPct > 0 && (
        <div
          className="bg-[#e12343]"
          style={{ width: `${risingPct}%` }}
        />
      )}
      {flatPct > 0 && (
        <div
          className="bg-[#999]"
          style={{ width: `${flatPct}%` }}
        />
      )}
      {fallingPct > 0 && (
        <div
          className="bg-[#1261c4]"
          style={{ width: `${fallingPct}%` }}
        />
      )}
    </div>
  );
}
