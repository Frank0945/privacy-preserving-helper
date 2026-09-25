import type { SliderParam } from "@/api/gen";
import { Button } from "@/components/atoms/button";
import { Slider } from "@/components/atoms/slider";
import { cn } from "cn";
import { Undo2Icon } from "lucide-react";

interface ParamSliderProps {
  value: number[];
  sliderParam: SliderParam;
  moveRestButtonOnTop: boolean;
  onValueChange: (value: number[]) => void;
}

const ParamSlider = ({
  value,
  sliderParam,
  moveRestButtonOnTop,
  onValueChange,
}: ParamSliderProps) => {
  return (
    <div>
      <div className="relative flex h-8.5 w-full items-end">
        {sliderParam.default != value[0] && (
          <Button
            size="sm"
            variant="outline"
            className={cn(
              "rounded-full",
              moveRestButtonOnTop && "absolute -top-full right-0",
            )}
            onClick={() => onValueChange([sliderParam.default ?? 0])}
          >
            <Undo2Icon />
            <span className="translate-y-px">還原為預設值</span>
          </Button>
        )}
        <div className="ml-auto text-base">
          {value + " " + sliderParam.unit}
        </div>
      </div>
      <Slider
        className="my-2"
        value={value}
        min={sliderParam.min ?? 0}
        max={sliderParam.max ?? 0}
        step={sliderParam.step ?? 0}
        onValueChange={onValueChange}
      />
      <div className="text-muted-foreground flex justify-between text-xs">
        <span>{sliderParam.min} (MIN)</span>
        <span>{sliderParam.max} (MAX)</span>
      </div>
    </div>
  );
};

export default ParamSlider;
