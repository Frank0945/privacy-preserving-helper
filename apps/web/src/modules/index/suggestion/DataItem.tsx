import {
  Item,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@/components/atoms/item";

const DataItem = () => {
  return (
    <Item variant="muted">
      <ItemContent>
        <ItemTitle>Basic Item</ItemTitle>
        <ItemDescription>
          A simple item with title and description.
        </ItemDescription>
      </ItemContent>
    </Item>
  );
};

export default DataItem;
