using System;

namespace GetGroupBoxMember.Services;

public class EmptyAttributeException : Exception
{
    public EmptyAttributeException()
    {
    }

    public EmptyAttributeException(string message)
        : base(message)
    {
    }

    public EmptyAttributeException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}
