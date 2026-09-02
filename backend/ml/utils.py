
import numpy as np


def find_sequences(array):
    """
    For each row in the array, find the start and end indices of sequences of ones,
    and store the transactions as tuples (start, end) in a separate array.

    Parameters:
        array (np.ndarray): 2D binary array with rows containing sequences of ones and zeros.

    Returns:
        list of list of tuples: Each inner list contains tuples (start, end) representing transactions.
    """
    transactions = []

    for row in array:
        # Find transitions using differences between adjacent elements
        diff = np.diff(row)

        # Start indices: where the difference is 1 (0 -> 1 transition)
        # Offset by 1 to get the correct index
        start_indices = np.where(diff == 1)[0] + 1

        # End indices: where the difference is -1 (1 -> 0 transition)
        end_indices = np.where(diff == -1)[0]

        # Special cases:
        # If the row starts with a 1, consider the first index as a start
        if row[0] == 1:
            start_indices = np.insert(start_indices, 0, 0)

        # If the row ends with a 1, consider the last index as an end
        if row[-1] == 1:
            end_indices = np.append(end_indices, len(row) - 1)

        # Pair up start and end indices into tuples and store them
        row_transactions = list(zip(start_indices, end_indices))
        transactions.append(row_transactions)

    return transactions

def generate_array_with_multiple_sequences(N, t_min, t_max, T=144):
    if t_min < 1 or t_min > T:
        raise ValueError("t_min must be between 1 and 144.")

    # Initialize the array with zeros
    array = np.zeros((N, T), dtype=int)

    for i in range(N):
        # Track the indices that have been used
        available_indices = list(range(T))

        while len(available_indices) >= t_min:
            # Randomly determine the length of the sequence of ones
            num_ones = np.random.randint(t_min, np.min(
                [t_max, len(available_indices)]) + 1)

            # Randomly pick a starting index from available slots
            start_idx = np.random.choice(available_indices[:-num_ones + 1])

            # Fill the sequence with ones
            array[i, start_idx:start_idx + num_ones] = 1

            # Mark these indices as used
            used_indices = range(start_idx, start_idx + num_ones)
            available_indices = [
                idx for idx in available_indices if idx not in used_indices]

    return array