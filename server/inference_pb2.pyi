from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class DataType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DT_UNSPECIFIED: _ClassVar[DataType]
    DT_FLOAT32: _ClassVar[DataType]
    DT_FLOAT64: _ClassVar[DataType]
    DT_INT32: _ClassVar[DataType]
    DT_INT64: _ClassVar[DataType]
    DT_BOOL: _ClassVar[DataType]
    DT_STRING: _ClassVar[DataType]
DT_UNSPECIFIED: DataType
DT_FLOAT32: DataType
DT_FLOAT64: DataType
DT_INT32: DataType
DT_INT64: DataType
DT_BOOL: DataType
DT_STRING: DataType

class PredictRequest(_message.Message):
    __slots__ = ("model_name", "input")
    MODEL_NAME_FIELD_NUMBER: _ClassVar[int]
    INPUT_FIELD_NUMBER: _ClassVar[int]
    model_name: str
    input: RequestTensor
    def __init__(self, model_name: _Optional[str] = ..., input: _Optional[_Union[RequestTensor, _Mapping]] = ...) -> None: ...

class PredictReply(_message.Message):
    __slots__ = ("outputs",)
    OUTPUTS_FIELD_NUMBER: _ClassVar[int]
    outputs: _containers.RepeatedCompositeFieldContainer[ResponseTensor]
    def __init__(self, outputs: _Optional[_Iterable[_Union[ResponseTensor, _Mapping]]] = ...) -> None: ...

class RequestTensor(_message.Message):
    __slots__ = ("dims", "name", "tensor_content")
    DIMS_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    TENSOR_CONTENT_FIELD_NUMBER: _ClassVar[int]
    dims: _containers.RepeatedScalarFieldContainer[int]
    name: str
    tensor_content: bytes
    def __init__(self, dims: _Optional[_Iterable[int]] = ..., name: _Optional[str] = ..., tensor_content: _Optional[bytes] = ...) -> None: ...

class ResponseTensor(_message.Message):
    __slots__ = ("dims", "name", "tensor_content", "data_type")
    DIMS_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    TENSOR_CONTENT_FIELD_NUMBER: _ClassVar[int]
    DATA_TYPE_FIELD_NUMBER: _ClassVar[int]
    dims: _containers.RepeatedScalarFieldContainer[int]
    name: str
    tensor_content: bytes
    data_type: DataType
    def __init__(self, dims: _Optional[_Iterable[int]] = ..., name: _Optional[str] = ..., tensor_content: _Optional[bytes] = ..., data_type: _Optional[_Union[DataType, str]] = ...) -> None: ...
